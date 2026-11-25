# Configurable `PreToolUse` `kubectl` Mutation Guard

- Feature ID: 2026-11-26-configurable-kubectl-mutation-guard
- Type: enhancement
- Status: In-Testing
- First entered In-Testing: 2026-11-26
- Related specifications: Extends [2026-11-18-lean-attention-guard-v2](../2026-11-18-lean-attention-guard-v2/spec.md)

## Problem and source intent

Relying solely on an `always_on` prompt rule to keep `kubectl` read-only outside personal lab clusters spends persistent prompt tokens on every turn regardless of task and fails to constrain subagents that do not inherit optional rules.

## Repository grounding

- [scripts/enforce-delegation.py](../../../scripts/enforce-delegation.py): Runs on every `run_command` `PreToolUse` invocation for both Primary Agent and subagents via `check_destructive_command()`.
- `~/.gemini/config/kubectl-guard.json` (or `AGY_KUBECTL_GUARD_CONFIG`): External per-operator allowlist keeping environment-specific cluster contexts and server endpoints out of the public plugin repository.

## Non-goals

- Wrapping `helm`, `k9s`, or `oc` in this initial scope (`kubectl` only).
- Hardcoding personal lab contexts or IP endpoints inside `antigravity-attention-guard-plugin`.

## Requirements

### REQ-047: Policy-driven `PreToolUse` `kubectl` mutation guard with lab allowlist

- Source intent: User approved D1 (`always_on` pruning + mechanical `kubectl` `PreToolUse` enforcement).
- Statement: WHEN a `kubectl-guard.json` policy configures `mode: "read_only_except_allowlist"`, `enforce-delegation.py` SHALL inspect `kubectl` segments inside `run_command` calls (including `rtk`/`sudo` prefixes, shell pipelines/chains, and `kubectl exec` remote payloads) and allow read-only operations universally while blocking mutating operations or mutating `exec` commands unless the target `--context`, `--server`, or kubeconfig `current-context` matches `mutable_contexts` or `mutable_servers`; and WHEN no policy file exists, `enforce-delegation.py` SHALL permit `kubectl` commands cleanly.
- AC-047-1 — Success: Read-only commands (`get`, `describe`, `logs`, `top`, `port-forward`, `rollout status|history`, `config view|get-contexts|current-context`, `auth can-i`, `--help`) and mutating commands explicitly targeting `mutable_contexts` or `mutable_servers` return `allow`, while missing policy defaults cleanly to `allow`.
- AC-047-2 — Boundary/failure: Mutating verbs (`apply`, `delete`, `patch`, `scale`, `rollout restart|undo`, `drain`, `cordon`, `taint`, `label`, `annotate`, `config delete-context`, unknown subcommands), mutating `kubectl exec` payloads (`rm`, `mv`, file `>`/`>>` redirects, `sed -i`, SQL `INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE`, `systemctl`/`service`), omitted `--context` resolving to a non-allowlisted or unreadable kubeconfig `current-context`, and malformed policy JSON files MUST return `deny`.
