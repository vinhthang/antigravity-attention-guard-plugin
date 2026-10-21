#!/usr/bin/env python3
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from common import is_subagent
from ledger import Ledger

PRIMARY_RULES_REMINDER = """⚡ Attention Guard Reminder (Turn Refresh):

Key Workflow Guidelines:
- Adaptive Planning: Multi-step architecture features and refactors require implementation_plan.md and human approval ('Proceed') before subagent execution. Quick one-offs may proceed directly.
- Problem Intolerance: Zero error suppression. No silent swallows or bare pass.
- Root Cause Diagnosis: On subagent failure, dispatch pro Diagnostician to isolate root causes (max 3 escalations).
- Execution Accountability: Subagents must return strict JSON schemas. Validate payloads using `rtk python3 scripts/payload_validator.py --role <role> --payload '<json>'`.

Continue with your current task."""

def build_refresh_reminder(
    conv_id: str,
    *args,
    token_budget: int = 128000,
    checkpoint_threshold: int = 80000,
    app_data_dir: str | None = None,
    ledger=None,
    total_tokens: int | None = None,
    artifact_dir: str | None = None,
    **kwargs,
) -> str:
    """Build dynamic context telemetry status line and pre-compaction state checkpoint (REQ-011)."""
    if len(args) >= 1:
        total_tokens = args[0]
    if len(args) >= 2:
        ledger = args[1]
    if len(args) >= 3:
        conv_id = args[2] or conv_id
    if len(args) >= 4:
        artifact_dir = args[3]

    if ledger is None:
        ledger = Ledger()

    if total_tokens is None:
        total_tokens, _ = ledger.get_session_token_stats(conv_id)

    pct = min(100.0, round((total_tokens / token_budget) * 100, 1)) if token_budget > 0 else 0.0
    budget_k = token_budget // 1000

    audit = {}
    if conv_id:
        try:
            audit = ledger.audit_conversation_budget(conv_id)
        except Exception as exc:
            _ = exc
            audit = {}

    unique_workers = audit.get("unique_workers", 0)
    prepared_workers = audit.get("prepared_workers", 0)

    base = app_data_dir or os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
    if not artifact_dir and conv_id and conv_id != "unknown":
        artifact_dir = os.path.join(base, "brain", conv_id)

    status_line = f"[Context Telemetry: ~{total_tokens:,} tokens ({pct}% of {budget_k}k budget) | Workers: {unique_workers}]"

    checkpoint_notice = ""
    if total_tokens >= checkpoint_threshold and artifact_dir:
        checkpoint_path = os.path.join(artifact_dir, "session_checkpoint.md")
        try:
            os.makedirs(artifact_dir, exist_ok=True)
            from datetime import datetime, timezone
            ts = datetime.now(timezone.utc).isoformat()
            checkpoint_content = (
                f"# Session State Checkpoint (Pre-Compaction Preservation)\n"
                f"- Timestamp: {ts}\n"
                f"- Context Tokens: ~{total_tokens:,} ({pct}% of {budget_k}k budget)\n"
                f"- Unique Workers: {unique_workers}\n"
                f"- Prepared Workers: {prepared_workers}\n\n"
                f"## Compaction Preservation Notice\n"
                f"This checkpoint was written automatically by Attention Guard prior to context window compaction.\n"
                f"When context compaction occurs, review this checkpoint to maintain continuity of in-flight tasks and worker delegations.\n"
            )
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                f.write(checkpoint_content)
            checkpoint_notice = (
                f"\n\n⚠️ Context Threshold Reached ({total_tokens:,} >= {checkpoint_threshold:,} tokens): "
                f"Pre-compaction state checkpoint written to `{checkpoint_path}`. "
                f"Review this checkpoint to preserve essential task state if context compaction occurs."
            )
        except OSError as exc:
            _ = exc

    return f"{PRIMARY_RULES_REMINDER}\n\n{status_line}{checkpoint_notice}"

def _emit_reminder(stdout, reminder_text=None):
    if reminder_text is None:
        reminder_text = PRIMARY_RULES_REMINDER
    if os.environ.get("AGY_ATTENTION_GUARD_OBSERVATION_MODE") == "1":
        stdout.write(json.dumps({}) + "\n")
    else:
        out = {
            "injectSteps": [
                {
                    "ephemeralMessage": reminder_text
                }
            ]
        }
        stdout.write(json.dumps(out, ensure_ascii=False) + "\n")

def main(argv=None, stdin=None, stdout=None):
    if stdin is None: stdin = sys.stdin
    if stdout is None: stdout = sys.stdout
    try:
        if os.environ.get("AGY_ATTENTION_GUARD_KILL_SWITCH") == "1":
            stdout.write(json.dumps({}) + "\n")
            return

        raw_payload = stdin.read()
        if not raw_payload or not raw_payload.strip():
            stdout.write(json.dumps({}) + "\n")
            return

        data = json.loads(raw_payload)

        # Do not refresh inside subagents
        is_sub, _, _, _, _ = is_subagent(data)
        if is_sub:
            stdout.write(json.dumps({}) + "\n")
            return

        # Default: every 25 invocations
        raw_interval = os.environ.get("AGY_ATTENTION_GUARD_REFRESH_INTERVAL", "25")
        try:
            interval = int(raw_interval)
            if interval <= 0:
                interval = 25
        except (ValueError, TypeError):
            interval = 25

        try:
            invocation_num = int(data.get("invocationNum", 0))
        except (ValueError, TypeError):
            invocation_num = 0

        session_id = data.get("sessionId") or data.get("session_id") or data.get("conversationId") or "default"
        conv_id = data.get("conversationId") or data.get("sessionId") or "unknown"
        artifact_dir = data.get("artifactDirectoryPath") or data.get("artifact_dir") or ""
        ledger = Ledger()

        transcript_path = data.get("transcriptPath", "")
        total_tokens = 0
        if transcript_path and os.path.exists(transcript_path):
            try:
                total_tokens = os.path.getsize(transcript_path) // 4
            except Exception as exc:
                _ = exc
                total_tokens = 0
        if total_tokens == 0:
            # Fallback to ledger session_stats
            total_tokens, _ = ledger.get_session_token_stats(session_id)

        last_refreshed = ledger.get_last_refreshed_tokens(session_id)
        tokens_since_refresh = max(0, total_tokens - last_refreshed)

        # Dynamic token volume trigger:
        if tokens_since_refresh >= 40000:
            ledger.record_refresh(session_id, total_tokens)
            ledger.reset_refresh_counter(session_id)
            reminder = build_refresh_reminder(conv_id, ledger=ledger, total_tokens=total_tokens, artifact_dir=artifact_dir)
            _emit_reminder(stdout, reminder)
            return

        # Checkpoint trigger on invocation_num > 0 and (invocation_num % interval == 0):
        if invocation_num > 0 and (invocation_num % interval == 0):
            if total_tokens < 20000:
                # Low token volume session: suppress static reminder
                stdout.write(json.dumps({}) + "\n")
                return
            else:
                ledger.record_refresh(session_id, total_tokens)
                ledger.reset_refresh_counter(session_id)
                reminder = build_refresh_reminder(conv_id, ledger=ledger, total_tokens=total_tokens, artifact_dir=artifact_dir)
                _emit_reminder(stdout, reminder)
                return

        stdout.write(json.dumps({}) + "\n")

    except Exception as exc:
        sys.stderr.write(f"Warning: Exception in attention-refresh: {exc}\n")
        stdout.write(json.dumps({}) + "\n")

if __name__ == "__main__":
    main()
