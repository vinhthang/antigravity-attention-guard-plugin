#!/usr/bin/env python3
"""Policy-driven PreToolUse kubectl mutation guard (REQ-047)."""

import json
import os
import re
import shlex
from typing import Optional

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.gemini/config/kubectl-guard.json")

_WRAPPER_BINS = frozenset({"rtk", "sudo", "env", "command", "nohup"})

_VALUE_FLAGS = frozenset(
    {
        "-n",
        "--namespace",
        "--context",
        "--kubeconfig",
        "-s",
        "--server",
        "-o",
        "--output",
        "-l",
        "--selector",
        "--field-selector",
        "--request-timeout",
        "-v",
        "--v",
        "--cluster",
        "--user",
        "--token",
        "--as",
        "--as-group",
        "--cache-dir",
        "-f",
        "--filename",
        "-c",
        "--container",
        "-p",
        "--patch",
    }
)

_READONLY_VERBS = frozenset(
    {
        "get",
        "describe",
        "logs",
        "top",
        "cluster-info",
        "explain",
        "api-resources",
        "api-versions",
        "version",
        "diff",
        "wait",
        "events",
        "port-forward",
    }
)

_READONLY_COMPOUND = {
    "rollout": frozenset({"status", "history"}),
    "config": frozenset({"view", "get-contexts", "current-context", "get-clusters", "get-users"}),
    "auth": frozenset({"can-i", "whoami"}),
}

_EXEC_MUTATION_BINS = frozenset(
    {
        "rm",
        "mv",
        "cp",
        "dd",
        "tee",
        "truncate",
        "chmod",
        "chown",
        "kill",
        "pkill",
        "killall",
        "systemctl",
        "service",
        "supervisorctl",
        "mkfs",
        "shutdown",
        "reboot",
    }
)

_EXEC_SQL_MUTATION_RE = re.compile(r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE)\b", re.IGNORECASE)
_INPLACE_EDIT_RE = re.compile(r"\b(?:sed|perl)\s+[^;&|]*-i\b")
_REDIRECT_RE = re.compile(r"(?:\d*>>?|\&>>?)\s*(\S+)")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(.*)$")


def _split_shell_segments(cmd_str: str) -> list[str]:
    """Split a shell command on unquoted ';', '&', '|', and newline."""
    segments: list[str] = []
    buf: list[str] = []
    quote: Optional[str] = None
    escaped = False
    n = len(cmd_str)
    i = 0
    while i < n:
        ch = cmd_str[i]
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\" and quote != "'":
            escaped = True
            buf.append(ch)
        elif ch in ("'", '"'):
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            buf.append(ch)
        elif quote is None and ch in (";", "&", "|", "\n"):
            seg = "".join(buf).strip()
            if seg:
                segments.append(seg)
            buf = []
            if ch in ("&", "|") and i + 1 < n and cmd_str[i + 1] == ch:
                i += 1
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        segments.append(tail)
    return segments


def _load_policy() -> tuple[Optional[dict], Optional[str]]:
    cfg_path = os.environ.get("AGY_KUBECTL_GUARD_CONFIG") or DEFAULT_CONFIG_PATH
    if not os.path.exists(cfg_path):
        return None, None
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return None, f"Attention Guard: Invalid kubectl-guard policy '{cfg_path}': {exc}"
    if not isinstance(data, dict):
        return None, f"Attention Guard: Invalid kubectl-guard policy '{cfg_path}': expected JSON object."
    mode = data.get("mode", "read_only_except_allowlist")
    if mode == "disabled":
        return None, None
    if mode != "read_only_except_allowlist":
        return None, f"Attention Guard: Unsupported kubectl-guard mode '{mode}'."
    return {
        "mutable_contexts": set(str(x) for x in data.get("mutable_contexts", [])),
        "mutable_servers": set(str(x).rstrip("/") for x in data.get("mutable_servers", [])),
    }, None


def _is_exec_mutating(exec_tokens: list[str]) -> bool:
    """Return True if remote exec command contains mutating file, process, or DB ops."""
    if not exec_tokens:
        return False
    joined = " ".join(exec_tokens)
    for sub in _split_shell_segments(joined):
        for match in _REDIRECT_RE.finditer(sub):
            target = match.group(1).strip("'\"")
            if target != "/dev/null":
                return True
        if _INPLACE_EDIT_RE.search(sub) or _EXEC_SQL_MUTATION_RE.search(sub):
            return True
        try:
            sub_toks = shlex.split(sub)
        except Exception:
            sub_toks = sub.split()
        while sub_toks and _ENV_ASSIGN_RE.match(sub_toks[0]):
            sub_toks.pop(0)
        if not sub_toks:
            continue
        cmd_bin = os.path.basename(sub_toks[0])
        if cmd_bin in _EXEC_MUTATION_BINS:
            return True
        if cmd_bin in ("sh", "bash", "zsh") and "-c" in sub_toks:
            idx = sub_toks.index("-c")
            if idx + 1 < len(sub_toks) and _is_exec_mutating([sub_toks[idx + 1]]):
                return True
    return False


def _read_kubeconfig_context(kubeconfig_override: Optional[str], inline_kubeconfig: Optional[str]) -> Optional[str]:
    raw = kubeconfig_override or inline_kubeconfig or os.environ.get("KUBECONFIG") or "~/.kube/config"
    for candidate in raw.split(os.pathsep):
        path = os.path.expanduser(candidate.strip())
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped.startswith("current-context:"):
                        val = stripped.split(":", 1)[1].strip().strip("'\"")
                        if val:
                            return val
        except OSError:
            continue
    return None


def _is_target_allowed(
    ctx: Optional[str],
    server: Optional[str],
    kubeconfig_override: Optional[str],
    inline_kubeconfig: Optional[str],
    policy: dict,
) -> tuple[bool, str]:
    contexts = policy["mutable_contexts"]
    servers = policy["mutable_servers"]
    if ctx is not None:
        return ctx in contexts, f"context '{ctx}'"
    if server is not None:
        norm = re.sub(r"^https?://", "", server).rstrip("/")
        host_only = norm.split(":", 1)[0]
        return (norm in servers or host_only in servers), f"server '{norm}'"
    resolved = _read_kubeconfig_context(kubeconfig_override, inline_kubeconfig)
    if resolved is None:
        return False, "unresolved kubeconfig current-context"
    return resolved in contexts, f"current-context '{resolved}'"


def check_kubectl_mutation(cmd_str: str) -> Optional[str]:
    """Return denial message if cmd_str runs a mutating kubectl op outside lab allowlist."""
    if not cmd_str or not isinstance(cmd_str, str):
        return None
    if "kubectl" not in cmd_str:
        return None

    policy, policy_err = _load_policy()
    if policy_err is not None:
        return policy_err
    if policy is None:
        return None

    clean_cmd = re.sub(r"\\\r?\n", " ", cmd_str)
    for seg in _split_shell_segments(clean_cmd):
        try:
            tokens = shlex.split(seg)
        except Exception:
            tokens = seg.split()

        inline_kubeconfig = None
        while tokens:
            m_env = _ENV_ASSIGN_RE.match(tokens[0])
            if m_env:
                if tokens[0].startswith("KUBECONFIG="):
                    inline_kubeconfig = m_env.group(1)
                tokens.pop(0)
            elif os.path.basename(tokens[0]) in _WRAPPER_BINS:
                tokens.pop(0)
            else:
                break

        if not tokens or os.path.basename(tokens[0]) != "kubectl":
            continue

        pre_dash = tokens[1 : tokens.index("--")] if "--" in tokens[1:] else tokens[1:]
        post_dash = tokens[tokens.index("--") + 1 :] if "--" in tokens[1:] else []

        ctx = None
        server = None
        kubeconfig_override = None
        has_help = False
        positionals: list[str] = []

        i = 0
        while i < len(pre_dash):
            tok = pre_dash[i]
            if tok in ("-h", "--help"):
                has_help = True
                i += 1
                continue
            if tok.startswith("--context="):
                ctx = tok.split("=", 1)[1]
                i += 1
                continue
            if tok.startswith("--kubeconfig="):
                kubeconfig_override = tok.split("=", 1)[1]
                i += 1
                continue
            if tok.startswith("--server="):
                server = tok.split("=", 1)[1]
                i += 1
                continue
            if tok in _VALUE_FLAGS:
                val = pre_dash[i + 1] if i + 1 < len(pre_dash) else ""
                if tok == "--context":
                    ctx = val
                elif tok == "--kubeconfig":
                    kubeconfig_override = val
                elif tok in ("-s", "--server"):
                    server = val
                i += 2
                continue
            if tok.startswith("-"):
                i += 1
                continue
            positionals.append(tok)
            i += 1

        if has_help or not positionals:
            continue

        verb = positionals[0]
        subverb = positionals[1] if len(positionals) > 1 else ""

        if verb in _READONLY_VERBS:
            continue
        if verb in _READONLY_COMPOUND and subverb in _READONLY_COMPOUND[verb]:
            continue
        if verb == "exec":
            remote = post_dash if post_dash else positionals[2:]
            if not _is_exec_mutating(remote):
                continue

        allowed, target_desc = _is_target_allowed(ctx, server, kubeconfig_override, inline_kubeconfig, policy)
        if not allowed:
            op_label = f"{verb} {subverb}".strip() if verb in _READONLY_COMPOUND else verb
            return (
                f"Attention Guard: Mutating kubectl '{op_label}' against {target_desc} is forbidden "
                f"(allowed only on configured mutable_contexts/mutable_servers)."
            )

    return None
