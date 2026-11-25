# Decisions: Configurable `PreToolUse` `kubectl` Mutation Guard

Governing specification: [spec.md](./spec.md)

## Architectural rationale

- Governs: `REQ-047`

Integrating `kubectl_guard.py` into the existing `enforce-delegation.py` `PreToolUse` hook adds zero extra Python subprocess overhead on `run_command` and governs both Primary Agent and subagents uniformly, while externalizing `mutable_contexts` and `mutable_servers` to `~/.gemini/config/kubectl-guard.json` keeps personal cluster identifiers out of the public plugin repo.

## ADR-008: Fail-closed `kubectl` verb & `current-context` inspection without shelling out

- Governs: `REQ-047`
- State: Accepted
- Context and constraints: Calling `kubectl config current-context` as a subprocess inside `PreToolUse` would add `50–150 ms` latency per command and fail inside sandboxed tests. Additionally, naive `re.split(r"[;&|]+")` splits inside `kubectl exec -- sh -c "cmd1; rm foo"` and misclassifies the remote payload as a separate host command.
- Decision: Use a quote-aware shell segment splitter in `scripts/kubectl_guard.py`, parse `kubectl` global flags and `--` `exec` payloads in-process, and scan `current-context:` directly from `--kubeconfig` / `KUBECONFIG` / `~/.kube/config` (`< 0.5 ms`), failing closed when context is unreadable or unlisted and when policy JSON is malformed.
- Affected components: `scripts/kubectl_guard.py`, `scripts/enforce-delegation.py`, `tests/test_kubectl_guard.py`.

## Gate 1: normative review

| Check | Status | Evidence / required correction |
| --- | --- | --- |
| Codebase grounding | PASS | Inspected `scripts/enforce-delegation.py::check_destructive_command`, `hooks.json`, and `tests/test_enforce_delegation.py`. |
| Attributable intent and explicit scope | PASS | Implements approved Decision D1 with explicit non-goals (`helm`/`k9s` excluded, zero personal IPs in repo). |
| Observable requirements and meaningful acceptance criteria | PASS | `AC-047-1` and `AC-047-2` specify exact verbs, `exec` payloads, kubeconfig fallback, and malformed JSON fail-closed behavior. |
| Assumptions and owner-deferred questions are explicit | PASS | `mode: read_only_except_allowlist` default when config absent is non-breaking (`allow`); zero `[PROVISIONAL]` items. |
| Architectural rationale respects requirements | PASS | `ADR-008` avoids subprocess latency while handling quoted `exec` payloads accurately. |
| IDs and references consistent | PASS | Allocates `REQ-047` and `ADR-008` above `REQ-046` / `ADR-007`. |
