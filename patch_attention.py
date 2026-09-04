with open('scripts/attention-check.py', 'r') as f:
    content = f.read()

content = content.replace('MAX_STOP_REJECTIONS = 2', 'MAX_STOP_REJECTIONS = 2')

old_logic = """    lower_content = last_model_content.lower()
    has_summary = "summary of skills used:" in lower_content or "no skills used" in lower_content

    if not has_summary:
        rejection_count = get_rejection_count(tracker)
        if rejection_count >= MAX_STOP_REJECTIONS:
            reset_rejection_count(tracker)
            print(json.dumps({"decision": "allow"}))
            return

        rejection_count = increment_rejection_count(tracker)

        injected_text = f"Attention Guard Watchdog: Your response is missing the mandatory 'Summary of skills used:' section. Please explicitly summarize the tools you invoked, or state 'No skills used' if none were required. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"

        print(json.dumps({"decision": "continue", "reason": injected_text}))
    else:
        reset_rejection_count(tracker)
        print(json.dumps({"decision": "allow"}))"""

new_logic = """    rejection_count = get_rejection_count(tracker)
    if rejection_count >= MAX_STOP_REJECTIONS:
        reset_rejection_count(tracker)
        print(json.dumps({"decision": "allow"}))
        return

    rejection_count = increment_rejection_count(tracker)

    injected_text = f"Attention Guard Refresh: Remember you are the Primary Agent. Delegate all execution to subagents. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"

    print(json.dumps({"decision": "continue", "reason": injected_text}))"""

content = content.replace(old_logic, new_logic)

with open('scripts/attention-check.py', 'w') as f:
    f.write(content)
