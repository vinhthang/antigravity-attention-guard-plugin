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

def _emit_reminder(stdout):
    if os.environ.get("AGY_ATTENTION_GUARD_OBSERVATION_MODE") == "1":
        stdout.write(json.dumps({}) + "\n")
    else:
        out = {
            "injectSteps": [
                {
                    "ephemeralMessage": PRIMARY_RULES_REMINDER
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
        ledger = Ledger()

        transcript_path = data.get("transcriptPath", "")
        total_tokens = 0
        if transcript_path and os.path.exists(transcript_path):
            try:
                total_tokens = os.path.getsize(transcript_path) // 4
            except Exception:
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
            _emit_reminder(stdout)
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
                _emit_reminder(stdout)
                return

        stdout.write(json.dumps({}) + "\n")

    except Exception as exc:
        sys.stderr.write(f"Warning: Exception in attention-refresh: {exc}\n")
        stdout.write(json.dumps({}) + "\n")

if __name__ == "__main__":
    main()
