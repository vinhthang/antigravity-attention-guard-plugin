#!/usr/bin/env python3
"""TDD tests for REQ-047: policy-driven PreToolUse kubectl mutation guard."""

import importlib.util
import io
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import kubectl_guard


def _load_enforce():
    spec = importlib.util.spec_from_file_location(
        "enforce_delegation_kubectl_test",
        str(SCRIPTS_DIR / "enforce-delegation.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_policy(tmp_path: Path, payload: object | None = None, raw: str | None = None) -> Path:
    policy_path = tmp_path / "kubectl-guard.json"
    if raw is not None:
        policy_path.write_text(raw, encoding="utf-8")
    else:
        data = payload or {
            "mode": "read_only_except_allowlist",
            "mutable_contexts": ["lab-bec1", "lab-k3s"],
            "mutable_servers": ["192.0.2.10:16443", "198.51.100.20"],
        }
        policy_path.write_text(json.dumps(data), encoding="utf-8")
    return policy_path


def _write_kubeconfig(path: Path, current_context: str) -> Path:
    path.write_text(
        f"apiVersion: v1\nkind: Config\ncurrent-context: {current_context}\n",
        encoding="utf-8",
    )
    return path


def _run_pretooluse(cmd: str) -> dict:
    mod = _load_enforce()
    stdin = io.StringIO(
        json.dumps(
            {
                "conversationId": "conv-primary-1",
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": cmd, "WaitMsBeforeAsync": 5000, "toolSummary": "Test"},
                },
            }
        )
    )
    stdout = io.StringIO()
    mod.main(stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())


def test_missing_policy_allows_kubectl(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(tmp_path / "does-not-exist.json"))
    assert kubectl_guard.check_kubectl_mutation("kubectl delete pod api-0 --context qa2") is None


def test_malformed_policy_fails_closed(tmp_path, monkeypatch):
    policy = _write_policy(tmp_path, raw="{not-json")
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))
    err = kubectl_guard.check_kubectl_mutation("kubectl delete pod api-0 --context lab-bec1")
    assert err is not None
    assert "policy" in err.lower()


@pytest.mark.parametrize(
    "cmd",
    [
        "rtk kubectl get pods -A --context qa2",
        "kubectl -n axon describe pod alert-0 --context staging",
        "kubectl logs -f pod/alert-0 --context qa3",
        "kubectl top pod -n default --context gke_prod",
        "kubectl port-forward svc/api 8080:80 --context qa2",
        "kubectl config get-contexts",
        "kubectl config view --minify",
        "kubectl rollout status deploy/app --context qa2",
        "kubectl rollout history deploy/app --context staging",
        "kubectl auth can-i get pods --context qa2",
        "kubectl delete --help",
        "kubectl apply -h",
    ],
)
def test_readonly_kubectl_commands_allowed_on_any_cluster(tmp_path, monkeypatch, cmd):
    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))
    assert kubectl_guard.check_kubectl_mutation(cmd) is None


@pytest.mark.parametrize(
    "cmd",
    [
        "kubectl apply -f manifest.yaml --context qa2",
        "rtk kubectl delete pod api-0 --context=gke_prod",
        "kubectl patch deploy app -p '{}' --context staging",
        "kubectl scale deploy app --replicas=0 --context qa3",
        "kubectl rollout restart deploy/app --context qa2",
        "kubectl drain node-1 --context staging",
        "kubectl cordon node-1 --context qa2",
        "kubectl taint nodes node-1 key=val:NoSchedule --context qa2",
        "kubectl label pod api-0 env=dev --context qa2",
        "kubectl annotate pod api-0 note=x --context qa2",
        "kubectl edit deploy/app --context qa2",
        "kubectl create namespace tmp --context qa2",
        "kubectl replace -f manifest.yaml --context qa2",
        "kubectl config delete-context staging",
        "kubectl unknownverb foo --context qa2",
    ],
)
def test_mutating_kubectl_blocked_on_non_allowlisted_context(tmp_path, monkeypatch, cmd):
    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))
    err = kubectl_guard.check_kubectl_mutation(cmd)
    assert err is not None
    assert "kubectl" in err.lower()


@pytest.mark.parametrize(
    "cmd",
    [
        "kubectl apply -f manifest.yaml --context lab-bec1",
        "rtk kubectl delete pod api-0 --context=lab-k3s",
        "kubectl rollout restart deploy/app --server https://192.0.2.10:16443",
        "kubectl scale deploy app --replicas=2 -s http://198.51.100.20:6443",
    ],
)
def test_mutating_kubectl_allowed_on_lab_contexts_and_servers(tmp_path, monkeypatch, cmd):
    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))
    assert kubectl_guard.check_kubectl_mutation(cmd) is None


def test_omitted_context_resolves_kubeconfig_and_fails_closed(tmp_path, monkeypatch):
    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))

    corp_cfg = _write_kubeconfig(tmp_path / "corp.yaml", "staging")
    lab_cfg = _write_kubeconfig(tmp_path / "lab.yaml", "lab-bec1")

    monkeypatch.setenv("KUBECONFIG", str(corp_cfg))
    assert kubectl_guard.check_kubectl_mutation("kubectl delete pod api-0") is not None
    assert kubectl_guard.check_kubectl_mutation(f"kubectl --kubeconfig {lab_cfg} delete pod api-0") is None
    assert kubectl_guard.check_kubectl_mutation(f"KUBECONFIG={lab_cfg} kubectl delete pod api-0") is None

    monkeypatch.setenv("KUBECONFIG", str(tmp_path / "missing.yaml"))
    assert kubectl_guard.check_kubectl_mutation("kubectl delete pod api-0") is not None


def test_chains_and_pipelines_checked_per_segment(tmp_path, monkeypatch):
    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))
    corp_cfg = _write_kubeconfig(tmp_path / "corp.yaml", "qa3")
    monkeypatch.setenv("KUBECONFIG", str(corp_cfg))

    assert kubectl_guard.check_kubectl_mutation("echo ok && rtk kubectl delete pod x --context qa3") is not None
    assert kubectl_guard.check_kubectl_mutation("cat m.yaml | kubectl apply -f -") is not None
    assert kubectl_guard.check_kubectl_mutation("echo ok && kubectl get pods -A") is None


@pytest.mark.parametrize(
    "cmd",
    [
        "kubectl exec -n qa2 pod-1 -- ps aux",
        'kubectl exec -n qa2 pod-1 -- sh -c "curl -s localhost:8080/health 2>/dev/null"',
        'kubectl exec -n qa2 pod-1 -- psql -c "SELECT count(*) FROM alerts"',
    ],
)
def test_readonly_kubectl_exec_allowed(tmp_path, monkeypatch, cmd):
    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))
    assert kubectl_guard.check_kubectl_mutation(cmd) is None


@pytest.mark.parametrize(
    "cmd",
    [
        "kubectl exec -n qa2 pod-1 -- rm -rf /tmp/cache",
        'kubectl exec -n qa2 pod-1 -- sh -c "echo x > /etc/cfg"',
        "kubectl exec -n qa2 pod-1 -- sed -i 's/a/b/' app.conf",
        'kubectl exec -n qa2 pod-1 -- psql -c "DELETE FROM users"',
        "kubectl exec -n qa2 pod-1 -- systemctl restart app",
    ],
)
def test_mutating_kubectl_exec_blocked_on_corporate_allowed_on_lab(tmp_path, monkeypatch, cmd):
    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))
    corp_cfg = _write_kubeconfig(tmp_path / "corp.yaml", "qa2")
    monkeypatch.setenv("KUBECONFIG", str(corp_cfg))

    assert kubectl_guard.check_kubectl_mutation(cmd) is not None
    lab_cmd = "kubectl --context lab-bec1 " + cmd.removeprefix("kubectl ")
    assert kubectl_guard.check_kubectl_mutation(lab_cmd) is None


def test_pretooluse_hook_integration(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))

    res_deny = _run_pretooluse("rtk kubectl delete pod api-0 --context qa2")
    assert res_deny["decision"] == "deny"
    assert "kubectl" in res_deny["reason"].lower()

    res_allow_lab = _run_pretooluse("rtk kubectl delete pod api-0 --context lab-bec1")
    assert res_allow_lab["decision"] == "allow"

    res_allow_ro = _run_pretooluse("rtk kubectl get pods -n axon --context qa2")
    assert res_allow_ro["decision"] == "allow"


def test_split_shell_segments_quotes_and_exec_nested_shell(tmp_path, monkeypatch):
    segs = kubectl_guard._split_shell_segments('echo "a;b" && echo \'c"d|e\' | cat &')
    assert segs == ['echo "a;b"', "echo 'c\"d|e'", "cat"]
    assert kubectl_guard._split_shell_segments("cmd1 | cmd2") == ["cmd1", "cmd2"]

    policy = _write_policy(tmp_path)
    monkeypatch.setenv("AGY_KUBECTL_GUARD_CONFIG", str(policy))
    assert kubectl_guard.check_kubectl_mutation('kubectl exec -n qa2 pod-1 -- sh -c "chmod 755 /app/run.sh"') is not None
    assert kubectl_guard.check_kubectl_mutation("kubectl exec -n qa2 pod-1 -- sh -c") is None
