#!/usr/bin/env python3
"""Ecosystem & SQLite Ledger Audit CLI (REQ-015).

Audits hooks configuration, agent markdown definitions, plugin surfaces,
and SQLite ledger database health across the Antigravity plugin ecosystem.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

# Add parent directory for sibling imports
sys.path.insert(0, os.path.dirname(__file__))

try:
    from surface_validator import validate_plugin_surface
except ImportError:
    validate_plugin_surface = None  # type: ignore

REQUIRED_SPEC_GATE_TOOLS = [
    "write_file",
    "edit_file",
    "write_to_file",
    "replace_file_content",
    "invoke_subagent",
]


def _extract_script_paths_from_command(command_str: str, base_dir: Path) -> List[Tuple[str, Path]]:
    """Extract candidate script file paths from a shell command string."""
    try:
        tokens = shlex.split(command_str)
    except Exception:
        tokens = command_str.split()

    results: List[Tuple[str, Path]] = []
    # Skip standard interpreters / wrappers
    interpreters = {"python", "python3", "bash", "sh", "node", "env"}

    for token in tokens:
        if token.startswith("-"):
            continue
        token_base = os.path.basename(token).lower()
        if token_base in interpreters:
            continue
        # Look for tokens that end with common script extensions or contain a path separator
        if (
            token.endswith((".py", ".sh", ".bash", ".js"))
            or "/" in token
            or "\\" in token
            or token.startswith(".")
            or token.startswith("~")
        ):
            raw_path = token
            if raw_path.startswith("~"):
                resolved = Path(raw_path).expanduser().resolve()
            elif os.path.isabs(raw_path):
                resolved = Path(raw_path).resolve()
            else:
                resolved = (base_dir / raw_path).resolve()
            results.append((raw_path, resolved))

    return results


def audit_hooks_config(hooks_path: Path) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Parse a hooks.json file and verify all command script paths and matchers.

    Returns:
        (is_valid, errors, info_dict)
    """
    p = Path(hooks_path).resolve()
    errors: List[str] = []
    info: Dict[str, Any] = {
        "hooks_path": str(p),
        "exists": p.is_file(),
        "groups": [],
        "scripts_verified": [],
    }

    if not p.is_file():
        errors.append(f"hooks.json not found: {p}")
        return False, errors, info

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        errors.append(f"Failed to parse JSON in {p}: {exc}")
        return False, errors, info

    base_dir = p.parent

    # Traverse hook groups: could be { "plugin-name": { "PreToolUse": [...] } } or { "PreToolUse": [...] }
    def audit_hook_list(hook_items: Any, group_name: str, hook_type: str, matcher_str: Optional[str] = None):
        if not isinstance(hook_items, list):
            return
        for item in hook_items:
            if not isinstance(item, dict):
                continue
            # If item has nested hooks (e.g. {"matcher": "...", "hooks": [...]})
            if "hooks" in item and isinstance(item["hooks"], list):
                sub_matcher = item.get("matcher", matcher_str)
                audit_hook_list(item["hooks"], group_name, hook_type, matcher_str=sub_matcher)
                continue

            cmd = item.get("command")
            if cmd and isinstance(cmd, str):
                scripts = _extract_script_paths_from_command(cmd, base_dir)
                for raw, resolved in scripts:
                    info["scripts_verified"].append(str(resolved))
                    if not resolved.exists():
                        errors.append(f"Hook script '{raw}' in {p} does not exist on disk: {resolved}")

    # Inspect top-level structure
    for key, value in data.items():
        if isinstance(value, dict):
            info["groups"].append(key)
            is_spec_gate = (
                "spec-gate" in key.lower()
                or (isinstance(value, dict) and any("spec-gate" in str(v).lower() for v in value.values()))
            )
            for event_name, event_val in value.items():
                if isinstance(event_val, list):
                    for entry in event_val:
                        if isinstance(entry, dict) and "matcher" in entry:
                            matcher_raw = entry.get("matcher", "")
                            # If this is spec-gate-plugin, verify matcher matches required tools
                            if is_spec_gate:
                                try:
                                    pat = re.compile(matcher_raw)
                                    for tool in REQUIRED_SPEC_GATE_TOOLS:
                                        if not (pat.search(tool) or pat.search(f"default_api:{tool}")):
                                            errors.append(
                                                f"spec-gate-plugin matcher regex in {p} does not match required tool '{tool}' (matcher: {matcher_raw})"
                                            )
                                except Exception as exc:
                                    errors.append(f"Invalid regex in matcher '{matcher_raw}': {exc}")
                            audit_hook_list(entry.get("hooks", []), key, event_name, matcher_str=matcher_raw)
                        elif isinstance(entry, dict) and "command" in entry:
                            audit_hook_list([entry], key, event_name)
        elif isinstance(value, list):
            # Top-level event list like { "PreToolUse": [...] }
            info["groups"].append(key)
            audit_hook_list(value, "default", key)

    return len(errors) == 0, errors, info


def audit_agents_dir(plugin_dir: Path) -> Tuple[bool, List[str]]:
    """Scan agents/*.md definitions and verify YAML frontmatter and tool parity.

    Checks:
        - Frontmatter contains name and description.
        - If tools are declared, any write_to_file agent includes write_file,
          and any view_file agent includes read_file.
    """
    pdir = Path(plugin_dir).resolve()
    agents_dir = pdir / "agents"
    errors: List[str] = []

    if not agents_dir.is_dir():
        return True, errors

    md_files = list(agents_dir.glob("*.md"))
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"Cannot read agent markdown {md_file}: {exc}")
            continue

        if not content.startswith("---"):
            errors.append(f"Agent {md_file.name} lacks YAML frontmatter ('---')")
            continue

        parts = content.split("---", 2)
        if len(parts) < 3:
            errors.append(f"Malformed YAML frontmatter in agent {md_file.name}")
            continue

        frontmatter_text = parts[1]
        fm_data: Dict[str, Any] = {}
        if yaml is not None:
            try:
                loaded = yaml.safe_load(frontmatter_text)
                if isinstance(loaded, dict):
                    fm_data = loaded
            except Exception as exc:
                errors.append(f"YAML parse error in agent {md_file.name}: {exc}")
                continue
        else:
            # Fallback naive YAML parser
            for line in frontmatter_text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm_data[k.strip()] = v.strip().strip("[]").replace('"', "").replace("'", "")

        name = fm_data.get("name")
        description = fm_data.get("description")

        if not name:
            errors.append(f"Agent {md_file.name} frontmatter missing required field 'name'")
        if not description:
            errors.append(f"Agent {md_file.name} frontmatter missing required field 'description'")

        tools_val = fm_data.get("tools")
        declared_tools: List[str] = []
        if isinstance(tools_val, list):
            declared_tools = [str(t).strip() for t in tools_val]
        elif isinstance(tools_val, str):
            declared_tools = [t.strip() for t in tools_val.split(",") if t.strip()]

        if declared_tools:
            if "write_to_file" in declared_tools and "write_file" not in declared_tools:
                errors.append(
                    f"Agent '{name or md_file.name}' in {md_file} declares legacy 'write_to_file' but lacks Antigravity 2.0 'write_file'"
                )
            if "view_file" in declared_tools and "read_file" not in declared_tools:
                errors.append(
                    f"Agent '{name or md_file.name}' in {md_file} declares legacy 'view_file' but lacks Antigravity 2.0 'read_file'"
                )

    return len(errors) == 0, errors


def audit_sqlite_ledger(db_path: Path, repair: bool = False) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Audit attention_guard.db ledger table counts and optionally repair stale rows.

    If repair=True:
        - Marks stale ACTIVE work_items older than 3600s as TERMINATED.
        - Deletes TIMED_OUT work_items older than 86400s so the ledger stays clean.
    """
    p = Path(db_path).resolve()
    errors: List[str] = []
    stats: Dict[str, Any] = {
        "db_path": str(p),
        "exists": p.is_file(),
    }

    if not p.is_file():
        errors.append(f"SQLite ledger database not found: {p}")
        return False, errors, stats

    now = time.time()
    try:
        conn = sqlite3.connect(str(p), timeout=5.0)
        conn.row_factory = sqlite3.Row

        # Tables census
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        stats["tables"] = tables

        work_items_counts: Dict[str, int] = {}
        if "work_items" in tables:
            rows = conn.execute("SELECT status, count(*) FROM work_items GROUP BY status").fetchall()
            for r in rows:
                work_items_counts[str(r[0])] = int(r[1])
            total_work_items = conn.execute("SELECT count(*) FROM work_items").fetchone()[0]
        else:
            errors.append("Table 'work_items' missing from SQLite ledger")
            total_work_items = 0

        stats["work_items"] = {
            "total": total_work_items,
            "counts": work_items_counts,
            "completed": work_items_counts.get("COMPLETED", 0),
            "active": work_items_counts.get("ACTIVE", 0),
            "timed_out": work_items_counts.get("TIMED_OUT", 0),
            "failed": work_items_counts.get("FAILED", 0),
            "terminated": work_items_counts.get("TERMINATED", 0),
        }

        if "events" in tables:
            total_events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
            event_counts = dict(conn.execute("SELECT type, count(*) FROM events GROUP BY type").fetchall())
        else:
            total_events = 0
            event_counts = {}

        stats["events"] = {
            "total": total_events,
            "counts_by_type": event_counts,
        }

        if repair and "work_items" in tables:
            # 1. Mark stale ACTIVE older than 3600s as TERMINATED
            active_cutoff = now - 3600.0
            cur_active = conn.execute(
                "UPDATE work_items SET status = 'TERMINATED', updated_at = ? "
                "WHERE status = 'ACTIVE' AND COALESCE(updated_at, created_at) < ?",
                (now, active_cutoff),
            )
            repaired_active = cur_active.rowcount

            # 2. Delete TIMED_OUT older than 86400s
            timeout_cutoff = now - 86400.0
            cur_timeout = conn.execute(
                "DELETE FROM work_items WHERE status = 'TIMED_OUT' AND COALESCE(updated_at, created_at) < ?",
                (timeout_cutoff,),
            )
            deleted_timeout = cur_timeout.rowcount

            conn.commit()
            stats["repair"] = {
                "active_marked_terminated": repaired_active,
                "stale_timed_out_deleted": deleted_timeout,
            }

            # Refresh counts post-repair
            repaired_counts = dict(
                conn.execute("SELECT status, count(*) FROM work_items GROUP BY status").fetchall()
            )
            stats["work_items"]["counts_after_repair"] = repaired_counts
            stats["work_items"]["total_after_repair"] = conn.execute(
                "SELECT count(*) FROM work_items"
            ).fetchone()[0]

        conn.close()
    except Exception as exc:
        errors.append(f"SQLite ledger audit exception: {exc}")
        return False, errors, stats

    return len(errors) == 0, errors, stats


def audit_ecosystem(
    plugins_root: Path = Path("~/.gemini/config/plugins").expanduser(),
    config_root: Path = Path("~/.gemini/config").expanduser(),
    db_path: Optional[Path] = None,
    repair_db: bool = False,
) -> Dict[str, Any]:
    """Audit config hooks, all installed plugins, and SQLite ledger database."""
    plugins_root = Path(plugins_root).expanduser().resolve()
    config_root = Path(config_root).expanduser().resolve()
    all_errors: List[str] = []

    # 1. Audit root config hooks.json
    config_hooks_path = config_root / "hooks.json"
    config_hooks_report: Dict[str, Any] = {}
    if config_hooks_path.is_file():
        is_ok, errs, info = audit_hooks_config(config_hooks_path)
        all_errors.extend(errs)
        config_hooks_report = info
        config_hooks_report["valid"] = is_ok
        config_hooks_report["errors"] = errs
    else:
        config_hooks_report = {"hooks_path": str(config_hooks_path), "exists": False}

    # 2. Audit all plugins under plugins_root
    plugins_report: Dict[str, Any] = {}
    if plugins_root.is_dir():
        for item in sorted(plugins_root.iterdir()):
            # Handle both directories and symlinks to directories
            try:
                target_p = item.resolve()
            except Exception:
                target_p = item
            if not target_p.is_dir():
                continue

            plugin_name = item.name
            p_errors: List[str] = []
            p_info: Dict[str, Any] = {
                "path": str(target_p),
                "symlink_target": str(target_p) if item.is_symlink() else None,
            }

            # 2a. Surface validation
            if validate_plugin_surface is not None:
                try:
                    s_ok, s_errs, s_census = validate_plugin_surface(target_p)
                    p_info["surface"] = s_census
                    if not s_ok:
                        p_errors.extend([f"[{plugin_name}] {e}" for e in s_errs])
                except Exception as exc:
                    p_errors.append(f"[{plugin_name}] surface_validator exception: {exc}")

            # 2b. Hooks audit
            hooks_candidates = [target_p / "hooks.json", target_p / "hooks" / "hooks.json"]
            p_info["hooks"] = []
            for h_candidate in hooks_candidates:
                if h_candidate.is_file():
                    h_ok, h_errs, h_info = audit_hooks_config(h_candidate)
                    p_info["hooks"].append(h_info)
                    if not h_ok:
                        p_errors.extend([f"[{plugin_name}] {e}" for e in h_errs])

            # 2c. Agents audit
            a_ok, a_errs = audit_agents_dir(target_p)
            p_info["agents"] = {"valid": a_ok, "errors": a_errs}
            if not a_ok:
                p_errors.extend([f"[{plugin_name}] {e}" for e in a_errs])

            p_info["valid"] = len(p_errors) == 0
            p_info["errors"] = p_errors
            plugins_report[plugin_name] = p_info
            all_errors.extend(p_errors)

    # 3. Audit SQLite Ledger
    if db_path is None:
        base_dir = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
        target_db = Path(base_dir) / "attention_guard.db"
    else:
        target_db = Path(db_path).expanduser().resolve()

    ledger_ok, ledger_errs, ledger_stats = audit_sqlite_ledger(target_db, repair=repair_db)
    if not ledger_ok:
        all_errors.extend(ledger_errs)
    ledger_stats["valid"] = ledger_ok
    ledger_stats["errors"] = ledger_errs

    return {
        "valid": len(all_errors) == 0,
        "errors": all_errors,
        "plugins": plugins_report,
        "ledger": ledger_stats,
        "config_hooks": config_hooks_report,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Antigravity Ecosystem & SQLite Ledger Audit CLI (REQ-015)")
    parser.add_argument(
        "--plugins-root",
        type=Path,
        default=Path("~/.gemini/config/plugins").expanduser(),
        help="Path to plugins directory",
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        default=Path("~/.gemini/config").expanduser(),
        help="Path to global config directory",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to attention_guard.db (defaults to standard location)",
    )
    parser.add_argument(
        "--repair-db",
        action="store_true",
        help="Mark stale ACTIVE work items as TERMINATED and delete old TIMED_OUT rows",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON results",
    )

    args = parser.parse_args(argv)

    report = audit_ecosystem(
        plugins_root=args.plugins_root,
        config_root=args.config_root,
        db_path=args.db_path,
        repair_db=args.repair_db,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"=== Antigravity Ecosystem Audit ===")
        print(f"Overall Valid: {report['valid']}")
        print(f"Total Errors : {len(report['errors'])}")
        if report["errors"]:
            print("\nErrors Found:")
            for e in report["errors"]:
                print(f"  - {e}")

        print(f"\n--- Plugins ({len(report['plugins'])}) ---")
        for pname, pdata in report["plugins"].items():
            status = "PASS" if pdata["valid"] else "FAIL"
            print(f"  [{status}] {pname} ({pdata.get('path', '')})")

        print(f"\n--- SQLite Ledger ({report['ledger'].get('db_path', '')}) ---")
        l_stats = report["ledger"].get("work_items", {})
        print(f"  Total Work Items: {l_stats.get('total', 0)}")
        print(f"  Counts Breakdown: {l_stats.get('counts', {})}")
        if "repair" in report["ledger"]:
            print(f"  Repairs Executed: {report['ledger']['repair']}")

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
