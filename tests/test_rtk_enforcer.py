#!/usr/bin/env python3
import json
import os
import subprocess
import sys
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
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "kubectl get pods -A"}}
        })
        assert result["decision"] == "allow"
        assert result["overwrite"]["CommandLine"] == "rtk kubectl get pods -A"

    def test_prepends_rtk_to_git(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git log --oneline"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" in result
        assert result["overwrite"]["CommandLine"] == "rtk git log --oneline"

    def test_prepends_rtk_to_docker(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "docker ps -a"}}
        })
        assert result["decision"] == "allow"
        assert result["overwrite"]["CommandLine"] == "rtk docker ps -a"

    def test_prepends_rtk_to_mvn(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "mvn clean compile"}}
        })
        assert result["decision"] == "allow"
        assert result["overwrite"]["CommandLine"] == "rtk mvn clean compile"

    def test_prepends_rtk_to_cargo(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "cargo test"}}
        })
        assert result["decision"] == "allow"
        assert result["overwrite"]["CommandLine"] == "rtk cargo test"

    def test_prepends_rtk_to_curl(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "curl -s https://example.com"}}
        })
        assert result["decision"] == "allow"
        assert result["overwrite"]["CommandLine"] == "rtk curl -s https://example.com"


class TestSkipAlreadyRTK:
    def test_skips_already_rtk(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "rtk kubectl get pods"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_skips_piped_to_rtk(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "oci compute list | rtk json"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result


class TestSkipNonCompatible:
    def test_skips_python3(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "python3 myscript.py"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_skips_java(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "java -jar app.jar"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_skips_echo(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "echo hello"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_skips_mkdir(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "mkdir -p /tmp/test"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_skips_chmod(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "chmod +x scripts/*.py"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_skips_cp(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "cp file1 file2"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_skips_node(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "node server.js"}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result


class TestEdgeCases:
    def test_non_run_command_skipped(self):
        result = run_hook({
            "toolCall": {"name": "write_to_file", "args": {}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_empty_command(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {"CommandLine": ""}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_empty_payload(self):
        result = subprocess.run(
            ["python3", SCRIPT],
            input="",
            capture_output=True, text=True, timeout=5
        )
        assert json.loads(result.stdout)["decision"] == "allow"


class TestRTKNotInstalled:
    def test_skips_when_rtk_not_installed(self):
        """Verify the hook gracefully skips when rtk binary is not found."""
        result = subprocess.run(
            [sys.executable, SCRIPT],
            input=json.dumps({
                "toolCall": {"name": "run_command", "args": {"CommandLine": "kubectl get pods"}}
            }),
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "PATH": ""}
        )
        output = json.loads(result.stdout)
        assert output["decision"] == "allow"
        assert "overwrite" not in output


