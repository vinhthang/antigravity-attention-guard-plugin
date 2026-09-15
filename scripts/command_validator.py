#!/usr/bin/env python3
"""
Command Security Validator for Attention Guard.
Enforces binary whitelisting, argument policy, path confinement, and P0 deployment boundary.
"""
import sys
import os
import shlex
import argparse
from typing import List, Optional, Tuple

ALLOWED_BINARIES = {
    "rtk", "pytest", "python3", "python", "git", "rsync",
    "echo", "mkdir", "cp", "rm", "test", "cat", "chmod", "mvn", "mvnw", "gradlew",
    "npm", "node", "npx", "go", "golangci-lint", "docker", "ssh", "make"
}

ALLOWED_GIT_SUBCOMMANDS = {"status", "diff", "log", "add", "commit", "fetch"}
FORBIDDEN_GIT_FLAGS = {"-C", "--git-dir", "--work-tree", "--exec-path"}

DEPLOYMENT_BASE_DIR = os.path.realpath(os.path.expanduser("~/.gemini/config/plugins"))

def get_allowed_cross_repo_pytest_paths():
    paths = set()
    env_override = os.environ.get("ATTENTION_GUARD_ALLOWED_PYTEST_DIR")
    if env_override:
        paths.add(os.path.realpath(env_override))
    home = os.path.expanduser("~")
    candidate = os.path.realpath(os.path.join(home, "github", "ai-review-plugin", "tests"))
    if os.path.exists(candidate):
        paths.add(candidate)
    return paths

def validate_command(command_str: str, workspace_root: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    if not command_str or not command_str.strip():
        return False, "Empty command string"

    if workspace_root is None:
        workspace_root = os.getcwd()
    workspace_root = os.path.realpath(workspace_root)

    # 1. Reject raw shell operators
    for token in command_str.split():
        if token in ("|", ">", ">>", "<", ";", "&&", "||"):
            return False, f"Shell operator '{token}' is forbidden; commands must be run as direct argv"

    try:
        tokens = shlex.split(command_str)
    except Exception as exc:
        return False, f"Failed to tokenize command: {exc}"

    if not tokens:
        return False, "Command token list is empty"

    # 2. Recursively unwrap rtk prefixes
    while tokens and tokens[0] == "rtk":
        tokens.pop(0)

    if not tokens:
        return False, "Command contains only rtk wrapper"

    binary = tokens[0]
    binary_name = os.path.basename(binary)

    # 3. Check binary whitelist
    if binary_name not in ALLOWED_BINARIES:
        return False, f"Binary '{binary_name}' is not in allowed binary whitelist"

    # 4. Check forbidden execution patterns
    if binary_name in ("bash", "sh", "zsh", "eval", "sudo"):
        return False, f"Direct invocation of shell interpreter '{binary_name}' is forbidden"

    # 5. Git subcommand policy
    if binary_name == "git":
        subcmd = None
        for arg in tokens[1:]:
            if arg in FORBIDDEN_GIT_FLAGS or any(arg.startswith(f + "=") for f in FORBIDDEN_GIT_FLAGS):
                return False, f"Forbidden git flag: '{arg}'"
            if not arg.startswith("-") and subcmd is None:
                subcmd = arg

        if subcmd is None:
            return False, "git invocation missing subcommand"
        if subcmd not in ALLOWED_GIT_SUBCOMMANDS:
            return False, f"git subcommand '{subcmd}' is forbidden. Allowed: {sorted(list(ALLOWED_GIT_SUBCOMMANDS))}"

    # 6. Python script policy
    is_deploy_script = False
    if binary_name in ("python3", "python"):
        for arg in tokens[1:]:
            if arg in ("-c", "-m") or arg.startswith("-c") or arg.startswith("-m"):
                return False, f"Python inline code execution flag '{arg}' is forbidden; execute scripts by file path"
            if not arg.startswith("-"):
                if arg.endswith(".py"):
                    expanded_s = os.path.expanduser(arg)
                    real_script = os.path.realpath(expanded_s if os.path.isabs(expanded_s) else os.path.join(workspace_root, expanded_s))
                    deploy_target = os.path.realpath(os.path.join(workspace_root, "scripts", "deploy_plugin.py"))
                    if real_script == deploy_target or os.path.basename(real_script) == "deploy_plugin.py":
                        is_deploy_script = True
                break

    # 7. Path confinement & P0 Deployment Directory Security
    for arg in tokens[1:]:
        if arg.startswith("-"):
            continue
        
        if "/" in arg or arg.endswith(".py") or arg.endswith(".json") or arg.endswith(".md"):
            expanded_arg = os.path.expanduser(arg)
            abs_arg = os.path.abspath(expanded_arg if os.path.isabs(expanded_arg) else os.path.join(workspace_root, expanded_arg))
            real_arg = os.path.realpath(abs_arg)
            
            # P0 Check: Elevated deployment directory access (lexical and realpath)
            in_deploy_dir = (
                abs_arg == DEPLOYMENT_BASE_DIR or
                os.path.commonpath([abs_arg, DEPLOYMENT_BASE_DIR]) == DEPLOYMENT_BASE_DIR or
                real_arg == DEPLOYMENT_BASE_DIR or
                os.path.commonpath([real_arg, DEPLOYMENT_BASE_DIR]) == DEPLOYMENT_BASE_DIR
            )
            if in_deploy_dir:
                if not is_deploy_script and os.path.basename(real_arg) != "peer_review.py":
                    return False, f"P0 Security Violation: Path '{arg}' targets plugin deployment directory outside deploy_plugin.py"
                continue

            # Cross-repo pytest read access
            if binary_name == "pytest":
                allowed_cross = get_allowed_cross_repo_pytest_paths()
                if any(real_arg == p or os.path.commonpath([real_arg, p]) == p for p in allowed_cross):
                    continue

            # Allow cross-repo execution of WorkBuddy
            if os.path.basename(real_arg) == "peer_review.py":
                continue

            # Standard workspace confinement check
            in_workspace = (
                real_arg == workspace_root or
                os.path.commonpath([real_arg, workspace_root]) == workspace_root
            )
            if not in_workspace:
                scratch_dir = os.path.realpath(os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity"))
                brain_dir = os.path.join(scratch_dir, "brain")
                if real_arg == brain_dir or os.path.commonpath([real_arg, brain_dir]) == brain_dir:
                    continue
                return False, f"Path traversal violation: argument '{arg}' resolves outside workspace ({real_arg})"

    return True, None

def run_tests() -> bool:
    home = os.path.expanduser("~")
    ws = os.path.realpath(os.path.join(home, "github", "ai-review-plugin", "attention-guard"))

    ok, err = validate_command("rtk pytest tests/test_dalio_conformance.py -v", ws)
    assert ok, f"Valid command failed: {err}"

    ok, err = validate_command("pytest tests/test_app.py | cat", ws)
    assert not ok, "Pipe operator should be rejected"

    ok, err = validate_command('python3 -c "import os"', ws)
    assert not ok, "python3 -c should be rejected"

    ok, err = validate_command("curl http://example.com", ws)
    assert not ok, "curl should be rejected"

    ok, err = validate_command("git push origin main", ws)
    assert not ok, "git push should be rejected"

    ok, err = validate_command("git status", ws)
    assert ok, f"git status failed: {err}"

    # P0 Security Check
    ok, err = validate_command("cp test.txt ~/.gemini/config/plugins/attention-guard/", ws)
    assert not ok, "P0: arbitrary binary targeting deployment dir should be rejected"
    assert "P0 Security Violation" in str(err)

    ok, err = validate_command("python3 scripts/deploy_plugin.py --deploy", ws)
    assert ok, f"P0: deploy_plugin.py should be permitted: {err}"

    test_path = os.path.join(home, "github", "ai-review-plugin", "tests", "test_peer_review.py")
    ok, err = validate_command(f"pytest {test_path}", ws)
    assert ok, f"Cross-repo pytest should be permitted: {err}"

    print("All command_validator self-tests PASSED.")
    return True

def main():
    parser = argparse.ArgumentParser(description="Validate command string against Attention Guard policy.")
    parser.add_argument("--cmd", help="Command string to validate")
    parser.add_argument("--workspace", default=os.getcwd(), help="Workspace root directory")
    parser.add_argument("--test", action="store_true", help="Run self-tests")
    args = parser.parse_args()

    if args.test:
        success = run_tests()
        sys.exit(0 if success else 1)

    if not args.cmd:
        parser.error("--cmd is required when not running --test")

    valid, err = validate_command(args.cmd, args.workspace)
    if valid:
        print("VALID")
        sys.exit(0)
    else:
        print(f"INVALID: {err}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
