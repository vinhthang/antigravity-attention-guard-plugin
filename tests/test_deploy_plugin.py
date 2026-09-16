import os
import sys
import pytest

# Ensure scripts dir is on sys.path
repo_root = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
scripts_dir = os.path.join(repo_root, "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from deploy_plugin import deploy, verify_source_bundle, CANONICAL_SOURCE

def test_deploy_symlink_self_copy_guard(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    for item in ["plugin.json", "hooks.json"]:
        (bundle_dir / item).write_text("{}", encoding="utf-8")
    for item in ["rules", "schemas", "scripts", "skills"]:
        sub = bundle_dir / item
        sub.mkdir()
        (sub / "dummy.txt").write_text("content", encoding="utf-8")

    # When source and target are the same realpath, deploy must return True immediately
    res = deploy(str(bundle_dir), str(bundle_dir))
    assert res is True

def test_verify_canonical_source_bundle():
    valid, missing = verify_source_bundle(CANONICAL_SOURCE)
    assert valid is True
    assert len(missing) == 0
