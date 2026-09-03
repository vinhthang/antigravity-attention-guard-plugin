import importlib.util
import sys
import os
spec = importlib.util.spec_from_file_location("rtk_enforcer", os.path.join(os.path.dirname(__file__), "../scripts/rtk-enforcer.py"))
rtk_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rtk_module)
should_prepend_rtk = rtk_module.should_prepend_rtk
split_env_prefix = rtk_module.split_env_prefix

import json
import subprocess
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "rtk-enforcer.py")


def run_hook(payload):
    result = subprocess.run(
        ["python3", SCRIPT],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=5
    )
    return json.loads(result.stdout)


class TestRTKEnforcement:
    def test_prepends_rtk_to_kubectl(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "kubectl get pods -A"}}})
        assert result["decision"] == "allow"
        assert result["overwrite"]["CommandLine"] == "rtk kubectl get pods -A"

    def test_prepends_rtk_to_git(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "git log --oneline"}}})
        assert result["overwrite"]["CommandLine"] == "rtk git log --oneline"

    def test_prepends_rtk_to_docker(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "docker ps -a"}}})
        assert result["overwrite"]["CommandLine"] == "rtk docker ps -a"

    def test_prepends_rtk_to_cargo(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "cargo test"}}})
        assert result["overwrite"]["CommandLine"] == "rtk cargo test"

    def test_prepends_rtk_with_single_env_var(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "RUST_LOG=debug cargo build"}}})
        assert result["overwrite"]["CommandLine"] == "RUST_LOG=debug rtk cargo build"

    def test_prepends_rtk_with_multiple_env_vars(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "FOO=bar RUST_LOG=debug cargo build"}}})
        assert result["overwrite"]["CommandLine"] == "FOO=bar RUST_LOG=debug rtk cargo build"

    def test_prepends_rtk_with_sudo(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "sudo cargo build"}}})
        assert result["overwrite"]["CommandLine"] == "sudo rtk cargo build"


class TestWordBoundaries:
    def test_git_matches_but_github_does_not(self):
        assert should_prepend_rtk("git log") is True
        assert should_prepend_rtk("github-cli list") is False

    def test_npm_matches_but_npm_malicious_does_not(self):
        assert should_prepend_rtk("npm install") is True
        assert should_prepend_rtk("npm-malicious exploit") is False

    def test_docker_compose_matches_before_docker(self):
        assert should_prepend_rtk("docker-compose up") is True
        assert should_prepend_rtk("docker ps") is True

    def test_ls_matches_standalone(self):
        assert should_prepend_rtk("ls -la") is True
        assert should_prepend_rtk("lsblk") is False

    def test_go_matches_standalone(self):
        assert should_prepend_rtk("go test ./...") is True
        assert should_prepend_rtk("gopher build") is False

    def test_pip3_matches_before_pip(self):
        assert should_prepend_rtk("pip3 install flask") is True
        assert should_prepend_rtk("pip install flask") is True
        assert should_prepend_rtk("pipeline run") is False

    def test_bare_command_matches(self):
        """Command with no arguments should still match."""
        assert should_prepend_rtk("git") is True
        assert should_prepend_rtk("kubectl") is True


class TestSkipAlreadyRTK:
    def test_skips_already_rtk(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "rtk kubectl get pods"}}})
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_skips_piped_to_rtk(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "oci compute list | rtk json"}}})
        assert result["decision"] == "allow"
        assert "overwrite" not in result


class TestSkipNonCompatible:
    def test_skips_python3(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "python3 myscript.py"}}})
        assert "overwrite" not in result

    def test_skips_echo(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "echo hello"}}})
        assert "overwrite" not in result

    def test_skips_non_compatible_with_env_vars(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": "FOO=bar python3 myscript.py"}}})
        assert "overwrite" not in result


class TestEdgeCases:
    def test_non_run_command_skipped(self):
        result = run_hook({"toolCall": {"name": "write_to_file", "args": {}}})
        assert "overwrite" not in result

    def test_empty_command(self):
        result = run_hook({"toolCall": {"name": "run_command", "args": {"CommandLine": ""}}})
        assert "overwrite" not in result

    def test_empty_payload(self):
        result = subprocess.run(["python3", SCRIPT], input="", capture_output=True, text=True, timeout=5)
        assert json.loads(result.stdout)["decision"] == "allow"


class TestRTKNotInstalled:
    def test_skips_when_rtk_not_installed(self):
        result = subprocess.run(
            [sys.executable, SCRIPT],
            input=json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "kubectl get pods"}}}),
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "PATH": ""}
        )
        output = json.loads(result.stdout)
        assert output["decision"] == "allow"
        assert "overwrite" not in output
