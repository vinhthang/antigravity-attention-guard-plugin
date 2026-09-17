#!/usr/bin/env python3
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from common import is_subagent

PRIMARY_RULES_REMINDER = """⚡ Attention Guard Reminder (Turn Refresh):

Key Workflow Guidelines:
- Adaptive Planning: Multi-step architecture features and refactors require implementation_plan.md and human approval ('Proceed') before subagent execution. Quick one-offs may proceed directly.
- Problem Intolerance: Zero error suppression. No silent swallows or bare pass.
- Root Cause Diagnosis: On subagent failure, dispatch pro Diagnostician (read-only, max 3 escalations).
- Execution Accountability: Delegate implementation to subagents; subagents must conform to schemas with execution_attempt_id.

Continue with your current task."""

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

        # Fast path: only trigger on positive multiples of interval
        if invocation_num <= 0 or (invocation_num % interval != 0):
            stdout.write(json.dumps({}) + "\n")
            return

        # Do not refresh inside subagents
        is_sub, _, _, _, _ = is_subagent(data)
        if is_sub:
            stdout.write(json.dumps({}) + "\n")
            return

        # Emit ephemeral reminder
        out = {
            "injectSteps": [
                {
                    "ephemeralMessage": PRIMARY_RULES_REMINDER
                }
            ]
        }
        if os.environ.get("AGY_ATTENTION_GUARD_OBSERVATION_MODE") == "1":
            stdout.write(json.dumps({}) + "\n")
        else:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")

    except Exception as exc:
        sys.stderr.write(f"Warning: Exception in attention-refresh: {exc}\n")
        stdout.write(json.dumps({}) + "\n")

if __name__ == "__main__":
    main()
