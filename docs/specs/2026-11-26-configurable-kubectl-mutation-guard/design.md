# Design: Configurable `PreToolUse` `kubectl` Mutation Guard

Sources: [spec.md](./spec.md), [decisions.md](./decisions.md)

## Components

| Requirement / AC | Path and symbol | Responsibility / change |
| --- | --- | --- |
| REQ-047 / AC-047-1, AC-047-2 | `scripts/kubectl_guard.py::check_kubectl_mutation`, `_split_shell_segments`, `_resolve_target_context_and_server` | Load optional policy JSON (`AGY_KUBECTL_GUARD_CONFIG` or `~/.gemini/config/kubectl-guard.json`), split command on unquoted shell operators, classify `kubectl` subcommands + `exec` payloads, resolve `--context`/`--server`/kubeconfig `current-context`, and return deny reason or `None`. |
| REQ-047 / AC-047-1, AC-047-2 | `scripts/enforce-delegation.py::check_destructive_command` | Delegate command validation to `check_kubectl_mutation(cmd_str)` after git/rm destructive checks so both direct callers and `main()` enforce the policy for Primary Agent and subagents. |
| REQ-047 / AC-047-1, AC-047-2 | `tests/test_kubectl_guard.py` | Unit and `PreToolUse` hook integration tests covering allowlist, read-only verbs, `exec` inspection, omitted `--context` kubeconfig resolution, pipelines, and malformed JSON fail-closed behavior. |

## Interfaces and flow

1. `load_kubectl_policy(config_path)` returns `None` when absent (no restriction), raises/returns error dict when JSON is invalid (`deny` fail-closed), or returns normalized `{mode, mutable_contexts, mutable_servers}`.
2. For each unquoted shell segment starting with `kubectl` (after stripping `rtk`, `sudo`, `env`, `command`, `nohup`, and `VAR=val` prefixes), extract global flags (`-n`, `--context`, `--kubeconfig`, `-s/--server`, etc.) and locate the subcommand verb.
3. Short-circuit `allow` if `--help`/`-h` or verb is strictly read-only (`get`, `describe`, `logs`, `top`, `cluster-info`, `explain`, `api-resources`, `api-versions`, `version`, `diff`, `wait`, `events`, `port-forward`, `auth can-i|whoami`, `rollout status|history`, `config view|get-contexts|current-context|get-clusters|get-users`).
4. For `exec`, inspect tokens after `--`: allow read-only commands (`ps`, `curl ... 2>/dev/null`, `SELECT ...`) and classify mutating shell ops/redirects (`>`/`>>` outside `/dev/null`, `rm`, `mv`, `chmod`, `chown`, `kill`, `sed -i`, `systemctl`, SQL `INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE`) as mutating.
5. For any mutating `kubectl` segment, resolve `--context` -> `--server` -> kubeconfig `current-context:` (from `--kubeconfig` / `$KUBECONFIG` / `~/.kube/config`); deny unless matched in `mutable_contexts` or `mutable_servers`.

## Boundaries and recovery

- Missing policy file -> `allow` (non-breaking default for external installs).
- Malformed policy JSON or unreadable/missing kubeconfig on a mutating command -> `deny` (fail-closed per `REQ-047` / `AC-047-2`).
