#!/usr/bin/env python3
"""
Verified Plugin Deployment Script for Attention Guard.
Verifies bundle integrity (plugin.json, hooks.json, rules, scripts, skills)
and safely synchronizes to ~/.gemini/config/plugins/attention-guard.
"""
import argparse
import json
import os
import shutil
import sys
from typing import List, Tuple

try:
    from surface_validator import validate_plugin_surface
except ImportError:
    cur_dir = os.path.dirname(__file__)
    if cur_dir not in sys.path:
        sys.path.insert(0, cur_dir)
    from surface_validator import validate_plugin_surface

CANONICAL_SOURCE = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
INSTALLED_TARGET = os.path.realpath(os.path.expanduser("~/.gemini/config/plugins/attention-guard"))
BUNDLE_ITEMS = ["plugin.json", "hooks.json", "rules", "scripts", "skills"]
OPTIONAL_BUNDLE_ITEMS = ["templates", "assets", "LICENSE", "README.md"]


def _prune_stale_entries(src_subdir: str, dst_subdir: str) -> None:
    if not (os.path.isdir(dst_subdir) and os.path.isdir(src_subdir)):
        return
    src_entries = set(os.listdir(src_subdir))
    for existing in os.listdir(dst_subdir):
        stale_p = os.path.join(dst_subdir, existing)
        if existing not in src_entries:
            if os.path.isfile(stale_p) or os.path.islink(stale_p):
                os.remove(stale_p)
            elif os.path.isdir(stale_p):
                shutil.rmtree(stale_p)
        elif os.path.isdir(stale_p) and os.path.isdir(os.path.join(src_subdir, existing)):
            _prune_stale_entries(os.path.join(src_subdir, existing), stale_p)


def verify_source_bundle(source_dir: str) -> Tuple[bool, List[str]]:
    missing = []
    for item in BUNDLE_ITEMS:
        item_path = os.path.join(source_dir, item)
        if not os.path.exists(item_path):
            missing.append(item)
            continue

        if item.endswith(".json"):
            try:
                with open(item_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                if item == "plugin.json":
                    logo = manifest.get("logo")
                    if logo and not os.path.exists(os.path.join(source_dir, logo)):
                        missing.append(f"manifest logo '{logo}' does not exist")
            except Exception as e:
                missing.append(f"{item} (invalid JSON: {e})")
        elif os.path.isdir(item_path):
            entries = os.listdir(item_path)
            if not entries:
                missing.append(f"{item} (empty directory)")

    if os.path.realpath(source_dir) == CANONICAL_SOURCE:
        for extra in ["templates", "assets", "LICENSE"]:
            extra_p = os.path.join(source_dir, extra)
            if not os.path.exists(extra_p):
                missing.append(extra)

    surf_ok, surf_errs, _ = validate_plugin_surface(source_dir)
    if not surf_ok:
        missing.extend(surf_errs)

    return len(missing) == 0, missing


def deploy(source_dir: str = CANONICAL_SOURCE, target_dir: str = INSTALLED_TARGET) -> bool:
    print(f"Verifying source bundle at {source_dir}...")
    valid, missing = verify_source_bundle(source_dir)
    if not valid:
        print(f"Pre-flight verification failed. Missing or invalid bundle items: {missing}", file=sys.stderr)
        return False

    print(f"Target deployment path: {target_dir}")
    if os.path.realpath(source_dir) == os.path.realpath(target_dir):
        print("Source and target resolve to the same directory (active symlink). No synchronization needed.")
        return True
    os.makedirs(target_dir, exist_ok=True)

    print("Syncing bundle files to target plugin...")
    target_schemas = os.path.join(target_dir, "schemas")
    if os.path.exists(target_schemas) and not os.path.exists(os.path.join(source_dir, "schemas")):
        if os.path.isdir(target_schemas):
            shutil.rmtree(target_schemas)
        else:
            os.remove(target_schemas)

    for sub in ("rules", "scripts", "skills", "templates"):
        _prune_stale_entries(os.path.join(source_dir, sub), os.path.join(target_dir, sub))

    for item in BUNDLE_ITEMS + OPTIONAL_BUNDLE_ITEMS:
        src_item = os.path.join(source_dir, item)
        if not os.path.exists(src_item):
            continue
        dst_item = os.path.join(target_dir, item)
        if os.path.isdir(src_item):
            shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
        else:
            shutil.copy2(src_item, dst_item)
    print("Deployment completed successfully.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Attention Guard deployment and verification tool.")
    parser.add_argument("--verify-only", action="store_true", help="Only verify source bundle without deploying")
    parser.add_argument("--deploy", action="store_true", help="Deploy plugin to ~/.gemini/config/plugins/attention-guard")
    parser.add_argument("--source", default=CANONICAL_SOURCE, help="Source directory")
    parser.add_argument("--target", default=INSTALLED_TARGET, help="Target installation path")
    args = parser.parse_args()

    if args.verify_only:
        valid, missing = verify_source_bundle(args.source)
        if valid:
            print("Source bundle is complete and valid.")
            sys.exit(0)
        else:
            print(f"Bundle verification failed: {missing}", file=sys.stderr)
            sys.exit(1)

    if args.deploy or not sys.argv[1:]:
        success = deploy(args.source, args.target)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
