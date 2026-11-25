# Verification: Configurable `PreToolUse` `kubectl` Mutation Guard

Governing specification: [spec.md](./spec.md)

## Planned checks

### AC-047-1 (REQ-047)

- Method: Run `pytest tests/test_kubectl_guard.py` verifying missing-policy allow, read-only verbs (`get`, `describe`, `logs`, `top`, `port-forward`, `rollout status`, `config get-contexts`, `auth can-i`, `--help`), read-only `exec`, and allowlisted `--context` / `--server` mutations.
- Expected outcome: All read-only and allowlisted cases return `allow` cleanly.

### AC-047-2 (REQ-047)

- Method: Run `pytest tests/test_kubectl_guard.py` and `mutation_runner.py` (`>= 80%`) covering mutating verbs (`apply`, `delete`, `patch`, `scale`, `rollout restart`, `drain`, `cordon`, `taint`, `label`, `annotate`, `config delete-context`), mutating `exec`, omitted `--context` kubeconfig resolution, shell chains, malformed policy JSON, and `PreToolUse` `enforce-delegation.py` subagent + Primary Agent integration.
- Expected outcome: All unauthorized mutations and malformed policy files return `deny`, and `mutation_runner.py` achieves `>= 80%`.

## Execution evidence

### Run 1 — 2026-11-26

- Environment: macOS, Python `3.11`, Antigravity `2.4`.
- Result: PASS (`AC-047-1`..`AC-047-2` passed).
- Full test suite (`PYTHONPATH=scripts rtk test pytest tests/`): **`169 passed, 1 warning in 2.41s`** (`0` failed).
- Mutation audit (`mutation_runner.py --target-file scripts/kubectl_guard.py --test-cmd "pytest -q tests/test_kubectl_guard.py"`): **`95.8%` (`23/24` killed)**.
- Plugin surface & deploy (`surface_validator.py --json` & `deploy_plugin.py`): **`valid: true` (`always_on_chars: 3887 / 8000`)**, synced live to `~/.gemini/config/plugins/attention-guard`.
- Live smoke test against deployed `enforce-delegation.py` + `~/.gemini/config/kubectl-guard.json`: `kubectl delete pod api-0 --context qa2` -> `deny`; `rtk kubectl delete pod api-0 --context pc1-bec1` -> `allow`; `rtk kubectl get pods -n axon --context qa2` -> `allow`.

## Real-world observations

No real-world confirmation has been recorded.
