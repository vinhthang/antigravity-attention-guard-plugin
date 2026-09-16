#!/usr/bin/env python3
"""
Verified Plugin Deployment Script for Attention Guard.
Verifies bundle integrity (plugin.json, hooks.json, rules, schemas, scripts)
and safely synchronizes to ~/.gemini/config/plugins/attention-guard.
"""
import sys
import os
import json
import shutil
import argparse
from typing import Tuple, List

CANONICAL_SOURCE = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
INSTALLED_TARGET = os.path.realpath(os.path.expanduser("~/.gemini/config/plugins/attention-guard"))
BUNDLE_ITEMS = ["plugin.json", "hooks.json", "rules", "schemas", "scripts", "skills"]

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
                    json.load(f)
            except Exception as e:
                missing.append(f"{item} (invalid JSON: {e})")
        elif os.path.isdir(item_path):
            entries = os.listdir(item_path)
            if not entries:
                missing.append(f"{item} (empty directory)")

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
    for item in BUNDLE_ITEMS:
        src_item = os.path.join(source_dir, item)
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
