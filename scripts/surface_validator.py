#!/usr/bin/env python3
"""
Antigravity Plugin Surface & Always-On Budget Validator.
Enforces component tree structure, character budgets, skill frontmatter/triggers,
Python script compilation, and hook event schema compliance.
Modeled on google-research/harness2/harness2/core/tree.py.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, List, Dict, Optional, Set, Any
import os
import sys
import re
import json
import argparse


@dataclass(frozen=True)
class PluginSurfaceSpec:
    name: str = "antigravity_plugin"
    always_on: tuple[str, ...] = ("rules/AGENTS.md",)
    always_on_max: int = 8000
    skill_dir: str = "skills"
    autotrigger_file: str = "rules/AGENTS.md"
    trigger_line: str = "- When {desc}, consult skill `{name}`.\n"
    hooks_file: str = "hooks.json"
    hook_events: frozenset[str] = frozenset({"PreInvocation", "PreToolUse", "PostToolUse", "Stop"})


DEFAULT_SURFACE = PluginSurfaceSpec()


def read_plugin_tree(
    plugin_dir: Path | str,
    surface: PluginSurfaceSpec = DEFAULT_SURFACE,
) -> dict[str, str]:
    """
    Reads all .md, .py, .json files under rules/, skills/, scripts/, schemas/,
    plus top-level hooks.json and plugin.json (ignoring __pycache__ and .pyc).
    Returns {rel_posix_path: content}.
    """
    pdir = Path(plugin_dir).resolve()
    tree: dict[str, str] = {}
    if not pdir.is_dir():
        return tree

    # Subdirectories to scan
    subdirs = ["rules", surface.skill_dir, "scripts", "schemas"]
    for sub in subdirs:
        sub_path = pdir / sub
        if not sub_path.is_dir():
            continue
        for fpath in sorted(sub_path.rglob("*")):
            if not fpath.is_file():
                continue
            if fpath.suffix not in {".md", ".py", ".json"}:
                continue
            rel = fpath.relative_to(pdir).as_posix()
            if "__pycache__" in fpath.parts or rel.endswith(".pyc"):
                continue
            try:
                tree[rel] = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

    # Top-level files
    top_candidates = {surface.hooks_file, "hooks.json", "plugin.json"}
    for fname in sorted(top_candidates):
        top_file = pdir / fname
        if top_file.is_file():
            try:
                tree[fname] = top_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

    return tree


def always_on_text(surface: PluginSurfaceSpec, tree: dict[str, str]) -> str:
    """
    Joins tree.get(a, "") for a in surface.always_on.
    If none of surface.always_on exist in tree, falls back to all_rules_text(tree).
    """
    found = [tree[a] for a in surface.always_on if a in tree]
    if not found:
        return all_rules_text(tree)
    return "\n".join(found)


def all_rules_text(tree: dict[str, str]) -> str:
    """
    Joins all rules/*.md files in tree.
    """
    return "\n".join(
        content for path, content in sorted(tree.items())
        if path.startswith("rules/") and path.endswith(".md")
    )


def skill_names(surface: PluginSurfaceSpec, tree: dict[str, str]) -> list[str]:
    """
    Returns sorted <name> for every skills/<name>/SKILL.md in tree.
    """
    names: set[str] = set()
    prefix = f"{surface.skill_dir}/"
    for path in tree:
        if path.startswith(prefix) and path.endswith("/SKILL.md"):
            sub = path[len(prefix):]
            parts = sub.split("/")
            if len(parts) == 2 and parts[1] == "SKILL.md":
                names.add(parts[0])
    return sorted(names)


def extract_frontmatter(content: str) -> dict[str, str]:
    """
    Extracts key-value pairs from YAML frontmatter between ^--- and ^---.
    """
    if not content.startswith("---"):
        return {}
    parts = re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return {}
    fm_text = parts[1]
    res: dict[str, str] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip("\"'")
            res[k] = v
    return res


def autotrigger(
    surface: PluginSurfaceSpec,
    tree: dict[str, str],
    *,
    always_on_max: int | None = None,
) -> list[str]:
    """
    For each skill in skill_names(surface, tree), if name is not mentioned in any
    rules/*.md in tree, extract description: from skills/<name>/SKILL.md frontmatter
    and append surface.trigger_line.format(name=name, desc=desc) to
    tree[surface.autotrigger_file] (before </instructions> if present, else at the end)
    provided len(always_on_text) + len(line) <= cap. Return list of repaired skill names.
    """
    cap = always_on_max if always_on_max is not None else surface.always_on_max
    repaired: list[str] = []

    for name in skill_names(surface, tree):
        rules_text = all_rules_text(tree)
        # Check if name is mentioned verbatim in any rules/*.md
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", rules_text):
            continue

        skill_file = f"{surface.skill_dir}/{name}/SKILL.md"
        content = tree.get(skill_file, "")
        fm = extract_frontmatter(content)
        desc = fm.get("description", "").strip()
        if not desc:
            continue
        desc = desc.rstrip(".")
        trigger = surface.trigger_line.format(name=name, desc=desc)
        if not trigger.endswith("\n"):
            trigger += "\n"

        target_file = surface.autotrigger_file
        orig_text = tree.get(target_file, "")

        if "</instructions>" in orig_text:
            idx = orig_text.rfind("</instructions>")
            new_text = orig_text[:idx] + trigger + orig_text[idx:]
        else:
            sep = "" if (not orig_text or orig_text.endswith("\n")) else "\n"
            new_text = orig_text + sep + trigger

        tree[target_file] = new_text
        if len(always_on_text(surface, tree)) <= cap:
            repaired.append(name)
        else:
            # Revert if cap exceeded
            tree[target_file] = orig_text

    return repaired


def _validate_hook_entry(
    hook_obj: Any,
    event_name: str,
    tree: dict[str, str],
    errs: list[str],
) -> None:
    if not isinstance(hook_obj, dict):
        errs.append(f"Hook command entry in '{event_name}' must be an object, got {type(hook_obj).__name__}")
        return
    htype = hook_obj.get("type")
    if htype != "command":
        errs.append(f"Hook in '{event_name}' must have type 'command', got '{htype}'")
    cmd = hook_obj.get("command")
    if not cmd or not isinstance(cmd, str) or not cmd.strip():
        errs.append(f"Hook in '{event_name}' must have a non-empty 'command'")
        return
    # Check script references: ./scripts/<file>.py or scripts/<file>.py
    for m in re.finditer(r'(?<![/\w])(?:\./)?scripts/([A-Za-z0-9_.\-/]+\.py)', cmd):
        rel_script = f"scripts/{m.group(1)}"
        if rel_script not in tree:
            errs.append(f"Hook command '{cmd}' references missing script '{rel_script}'")


def check_hooks(
    surface: PluginSurfaceSpec,
    src: str,
    tree: dict[str, str],
    errs: list[str],
) -> None:
    """
    Validates hooks.json. Supports both {"hooks": {"PreToolUse": [...]}} and
    named group objects like {"attention-guard-plugin": {"PreToolUse": [...]}}.
    Verifies every event key is in surface.hook_events, event maps to non-empty
    list of entries, type is command, non-empty command, and local script targets exist.
    """
    try:
        data = json.loads(src)
    except Exception as e:
        errs.append(f"Invalid JSON in {surface.hooks_file}: {e}")
        return

    if not isinstance(data, dict):
        errs.append(f"Top-level structure in {surface.hooks_file} must be a JSON object")
        return

    # Normalize groups to list of (group_name, event_dict)
    groups: list[tuple[str, dict]] = []
    if "hooks" in data and isinstance(data["hooks"], dict):
        groups.append(("hooks", data["hooks"]))
    else:
        has_list = any(isinstance(v, list) for v in data.values())
        has_dict = any(isinstance(v, dict) for v in data.values())
        if has_list and not has_dict:
            groups.append(("root", data))
        elif has_dict and not has_list:
            for k, v in data.items():
                if isinstance(v, dict):
                    groups.append((k, v))
                else:
                    errs.append(f"Expected dict for hook group '{k}', got {type(v).__name__}")
        elif not data:
            groups = []
        else:
            root_events: dict[str, Any] = {}
            for k, v in data.items():
                if isinstance(v, dict):
                    groups.append((k, v))
                else:
                    root_events[k] = v
            if root_events:
                groups.append(("root", root_events))

    for group_name, event_dict in groups:
        if not isinstance(event_dict, dict):
            errs.append(f"Hook group '{group_name}' must be a JSON object")
            continue
        for event_name, entries in event_dict.items():
            if event_name not in surface.hook_events:
                errs.append(
                    f"Invalid hook event '{event_name}' in '{group_name}' "
                    f"(expected one of {sorted(surface.hook_events)})"
                )
                continue
            if not isinstance(entries, list) or len(entries) == 0:
                errs.append(f"Hook event '{event_name}' in '{group_name}' must map to a non-empty list of entries")
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    errs.append(f"Entry in '{event_name}' must be an object, got {type(entry).__name__}")
                    continue
                if "hooks" in entry:
                    sub_hooks = entry.get("hooks")
                    if not isinstance(sub_hooks, list) or len(sub_hooks) == 0:
                        errs.append(f"Matcher entry in '{event_name}' must contain a non-empty 'hooks' list")
                        continue
                    for h in sub_hooks:
                        _validate_hook_entry(h, event_name, tree, errs)
                else:
                    _validate_hook_entry(entry, event_name, tree, errs)


def validate_plugin_surface(
    plugin_dir: Path | str,
    *,
    surface: PluginSurfaceSpec = DEFAULT_SURFACE,
    always_on_max: int | None = None,
    repair_triggers: bool = False,
) -> tuple[bool, list[str], dict]:
    """
    Validates a plugin directory against PluginSurfaceSpec rules.
    Returns (is_valid, errs, census_dict).
    """
    pdir = Path(plugin_dir).resolve()
    tree = read_plugin_tree(pdir, surface)
    cap = always_on_max if always_on_max is not None else surface.always_on_max
    errs: list[str] = []

    # Optional trigger auto-repair
    if repair_triggers:
        repaired = autotrigger(surface, tree, always_on_max=cap)
        if repaired and surface.autotrigger_file in tree:
            target_path = pdir / surface.autotrigger_file
            try:
                target_path.write_text(tree[surface.autotrigger_file], encoding="utf-8")
            except Exception as e:
                errs.append(f"Failed to write repaired triggers to '{surface.autotrigger_file}': {e}")

    # 1. Always-on budget check
    aon = always_on_text(surface, tree)
    aon_len = len(aon)
    if aon_len > cap:
        errs.append(f"Always-on rules exceed budget: {aon_len} > {cap} chars")

    for a in surface.always_on:
        if a in tree and not tree[a].strip():
            errs.append(f"Always-on rule file '{a}' is empty")

    # 2. Skills frontmatter & trigger checks
    rules_text = all_rules_text(tree)
    skills = skill_names(surface, tree)
    for name in skills:
        skill_path = f"{surface.skill_dir}/{name}/SKILL.md"
        skill_content = tree.get(skill_path, "")
        fm = extract_frontmatter(skill_content)
        desc = fm.get("description", "").strip()
        if not desc:
            errs.append(f"Skill '{name}' in '{skill_path}' missing non-empty 'description:' in frontmatter")
        fm_name = fm.get("name")
        if fm_name and fm_name != name:
            errs.append(f"Skill '{name}' has mismatched name '{fm_name}' in frontmatter")
        if not re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", rules_text):
            errs.append(f"Skill '{name}' is not triggered in any rules/*.md")

    # 3. Python scripts compilation
    for rel_path, content in sorted(tree.items()):
        if not rel_path.endswith(".py"):
            continue
        is_script = rel_path.startswith("scripts/")
        is_skill_script = rel_path.startswith(f"{surface.skill_dir}/") and "/scripts/" in rel_path
        if is_script or is_skill_script:
            try:
                compile(content, rel_path, "exec")
            except SyntaxError as e:
                errs.append(f"Python syntax error in '{rel_path}' line {e.lineno}: {e.msg}")
            except Exception as e:
                errs.append(f"Failed to compile '{rel_path}': {e}")

    # 4. Scans rules/*.md and skills/*/SKILL.md for script references
    for rel_path, content in sorted(tree.items()):
        is_rule_md = rel_path.startswith("rules/") and rel_path.endswith(".md")
        is_skill_md = rel_path.startswith(f"{surface.skill_dir}/") and rel_path.endswith("/SKILL.md")
        if not (is_rule_md or is_skill_md):
            continue
        skill_name = None
        if is_skill_md:
            parts = rel_path.split("/")
            if len(parts) >= 2:
                skill_name = parts[1]

        # Check absolute path references
        for m in re.finditer(r'(/[\w.\-]+(?:/[\w.\-]+)*/scripts/[A-Za-z0-9_.\-/]+\.py)', content):
            abs_path = m.group(1)
            if not os.path.exists(abs_path):
                errs.append(f"Referenced absolute script '{abs_path}' in '{rel_path}' does not exist on disk")

        # Check relative path references
        for m in re.finditer(r'(?<![/\w])(?:\./)?scripts/([A-Za-z0-9_.\-/]+\.py)', content):
            sub = m.group(1)
            candidate1 = f"scripts/{sub}"
            candidate2 = f"{surface.skill_dir}/{skill_name}/scripts/{sub}" if skill_name else None
            if candidate1 not in tree and (not candidate2 or candidate2 not in tree):
                errs.append(f"Referenced script 'scripts/{sub}' in '{rel_path}' not found in plugin tree")

    # 5. Check hooks.json if present
    hooks_file_to_check = None
    if surface.hooks_file in tree:
        hooks_file_to_check = surface.hooks_file
    elif "hooks.json" in tree:
        hooks_file_to_check = "hooks.json"

    if hooks_file_to_check:
        check_hooks(surface, tree[hooks_file_to_check], tree, errs)

    census = {
        "plugin_dir": str(pdir),
        "always_on_chars": aon_len,
        "always_on_max": cap,
        "skills": skills,
        "skill_count": len(skills),
        "scripts_count": len([p for p in tree if p.endswith(".py")]),
        "files_count": len(tree),
        "valid": len(errs) == 0,
        "errors": list(errs),
    }

    return len(errs) == 0, errs, census


def diff_summary(
    surface: PluginSurfaceSpec,
    before: dict[str, str],
    after: dict[str, str],
) -> dict[str, Any]:
    """
    Returns diff metrics between before and after plugin trees:
    {"added": ..., "removed": ..., "modified": ..., "always_on_char_delta": ...}
    """
    b_keys = set(before.keys())
    a_keys = set(after.keys())
    added = sorted(list(a_keys - b_keys))
    removed = sorted(list(b_keys - a_keys))
    modified = sorted([k for k in (b_keys & a_keys) if before[k] != after[k]])
    delta = len(always_on_text(surface, after)) - len(always_on_text(surface, before))
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "always_on_char_delta": delta,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity Plugin Surface Validator")
    parser.add_argument("--plugin-dir", default=".", help="Path to plugin directory")
    parser.add_argument("--always-on-max", type=int, default=8000, help="Max characters for always-on rules")
    parser.add_argument("--autotrigger", action="store_true", help="Automatically repair missing skill trigger lines")
    parser.add_argument("--json", action="store_true", help="Output census as JSON")
    args = parser.parse_args()

    ok, errs, census = validate_plugin_surface(
        args.plugin_dir,
        always_on_max=args.always_on_max,
        repair_triggers=args.autotrigger,
    )

    if args.json:
        print(json.dumps(census, indent=2))
    else:
        if ok:
            print(f"Plugin surface valid ({census['skill_count']} skills, {census['always_on_chars']}/{census['always_on_max']} always-on chars)")
        else:
            print(f"Plugin surface validation failed with {len(errs)} error(s):", file=sys.stderr)
            for err in errs:
                print(f"  - {err}", file=sys.stderr)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
