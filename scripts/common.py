import sys
import os
import json
import re
import shlex
from ledger import Ledger

DEFAULT_THINKING_MODELS = ["opus", "gemini-4", "gemini 4"]

def get_primary_model(data=None):
    if isinstance(data, dict):
        model = data.get("modelName") or data.get("model") or data.get("model_name")
        if model:
            return str(model).strip()
    env_model = os.environ.get("AGY_PRIMARY_MODEL") or os.environ.get("ANTIGRAVITY_MODEL")
    if env_model:
        return env_model.strip()
    return ""

def is_thinking_model(model_name):
    if not model_name or not isinstance(model_name, str):
        return False
    env_models = os.environ.get("ATTENTION_GUARD_THINKING_MODELS")
    if env_models:
        candidates = [m.strip().lower() for m in env_models.split(",") if m.strip()]
    else:
        candidates = [m.lower() for m in DEFAULT_THINKING_MODELS]
    name_lower = model_name.lower()
    return any(cand in name_lower for cand in candidates)

def is_markdown_file(file_path):
    if not file_path or not isinstance(file_path, str):
        return False
    path_lower = file_path.lower()
    return path_lower.endswith(".md") or path_lower.endswith(".markdown")

def is_build_command(cmd_str):
    if not cmd_str or not isinstance(cmd_str, str):
        return False
    try:
        tokens = shlex.split(cmd_str)
    except Exception:
        tokens = cmd_str.split()
    while tokens and tokens[0] == "rtk":
        tokens.pop(0)
    if not tokens:
        return False

    bin_name = os.path.basename(tokens[0]).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if bin_name.endswith(ext):
            bin_name = bin_name[:-len(ext)]
            break

    # Direct build tools / generators
    if bin_name in {"make", "cmake", "ninja"}:
        return True

    # Python pip
    if bin_name in {"pip", "pip3"}:
        return True

    # python -m pip ... or python setup.py ...
    if bin_name in {"python", "python3"}:
        i = 1
        while i < len(tokens):
            arg = tokens[i]
            if arg == "-m":
                if i + 1 < len(tokens):
                    return tokens[i + 1].lower() == "pip"
                return False
            if arg.startswith("-m") and len(arg) > 2:
                return arg[2:].lower() == "pip"
            if arg == "-c":
                return False
            if arg in {"-W", "-X", "--check-hash-based-pycs"}:
                i += 2
                continue
            if arg.startswith("-"):
                i += 1
                continue
            script_base = os.path.basename(arg).lower()
            if script_base == "setup.py":
                return any(t.lower() in {"build", "install", "bdist_wheel", "sdist", "develop"} for t in tokens[i + 1:])
            return False
        return False

    # Cargo
    if bin_name == "cargo":
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"build", "check", "install"} for t in lower_tokens):
            return True

    # Go
    if bin_name == "go":
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"build", "install"} for t in lower_tokens):
            return True

    # Node / JS
    if bin_name in {"npm", "pnpm", "yarn", "bun"}:
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"install", "i", "ci", "add", "build", "compile"} for t in lower_tokens):
            return True
        if "run" in lower_tokens and any(t in {"build", "compile"} for t in lower_tokens):
            return True

    # Java / JVM build tools
    if bin_name in {"mvn", "mvnw"}:
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"compile", "install", "package", "verify", "build"} for t in lower_tokens):
            return True

    if bin_name in {"gradle", "gradlew"}:
        lower_tokens = [t.lower() for t in tokens[1:]]
        if any(t in {"build", "compile", "assemble", "install"} for t in lower_tokens):
            return True

    return False

def get_cache_dir():
    base = os.environ.get("AGY_APP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    return cache

def get_turn_state(transcript_path):
    turn_id = 0
    lines_count = 0
    if not transcript_path or not os.path.exists(transcript_path):
        return turn_id, lines_count
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    lines_count += 1
                    try:
                        step = json.loads(line)
                        if str(step.get("source", "")).startswith("USER") and step.get("type") == "USER_INPUT":
                            turn_id = step.get("step_index", turn_id)
                    except Exception as exc:
                        sys.stderr.write(f"Warning: {exc}\n")
    except Exception as exc:
        sys.stderr.write(f"Warning: {exc}\n")
    return turn_id, lines_count

def is_subagent(data):
    transcript_path = data.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        return False, False, 0, None, None

    conv_id = data.get("conversationId", "unknown")
    turn_id, _ = get_turn_state(transcript_path)
    
    try:
        tokens = []
        token_pattern = re.compile(r'\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]')
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    step = json.loads(line_str)
                    if step.get("type") in ("USER_INPUT", "SYSTEM_MESSAGE"):
                        content = step.get("content", "")
                        for match in token_pattern.finditer(content):
                            tok = match.group(1)
                            if tok not in tokens:
                                tokens.append(tok)
                except Exception:
                    continue

        ledger = Ledger()
        for token in reversed(tokens):
            with ledger._get_connection() as conn:
                cursor = conn.execute("SELECT payload FROM events WHERE type = 'WORK_PREPARED' AND payload LIKE ?", (f'%"{token}"%',))
                row = cursor.fetchone()
                if row:
                    payload_data = json.loads(row[0])
                    may_delegate = payload_data.get("may_delegate", False)
                    remaining_depth = payload_data.get("remaining_depth", 0)
                    parent_conv_id = payload_data.get("parent_conv_id", "unknown")
                    parent_turn_id = payload_data.get("parent_turn_id", "unknown")

                    if conv_id == parent_conv_id:
                        continue

                    if ledger.claim_token(token, conv_id):
                        ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "WORK_CLAIMED")
                        ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "RUNNING")
                        return True, may_delegate, remaining_depth, parent_conv_id, parent_turn_id

        if os.environ.get("AGY_DISABLE_SENDER_FALLBACK") != "1":
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str:
                            continue
                        try:
                            step = json.loads(line_str)
                            if step.get("source") == "SYSTEM" and step.get("type") == "SYSTEM_MESSAGE":
                                content = str(step.get("content") or "")
                                m = re.search(r"\bsender=([0-9a-fA-F\-]{36})\b", content)
                                if m:
                                    parent_conv_id = m.group(1)
                                    if parent_conv_id != conv_id:
                                        return True, False, 0, parent_conv_id, "0"
                            break
                        except Exception:
                            break
            except Exception as exc:
                sys.stderr.write(f"Warning in is_subagent sender fallback: {exc}\n")

    except Exception as exc:
        sys.stderr.write(f"Error in is_subagent: {exc}\n")

    return False, False, 0, None, None
