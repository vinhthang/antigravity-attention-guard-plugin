import re

with open('scripts/inject-rules.py', 'r') as f:
    content = f.read()

content = content.replace('"AGENTS.md"', '"EXECUTOR.md"')

old_try_except = """                try:
                    token_file = os.path.join(cache_dir, f"agy_issued_token_{token}")
                    with open(token_file, "w") as f:
                        json.dump({"issuer": parent_conv_id, "recipient": None}, f)
                except Exception:
                    pass"""

new_try_except = """                try:
                    token_file = os.path.join(cache_dir, f"agy_issued_token_{token}")
                    with open(token_file, "w") as f:
                        json.dump({"issuer": parent_conv_id, "recipient": None}, f)
                except Exception:
                    print(json.dumps({"decision": "deny", "reason": "Attention Guard: Failed to issue cryptographic token to subagent cache."}))
                    return"""

content = content.replace(old_try_except, new_try_except)

with open('scripts/inject-rules.py', 'w') as f:
    f.write(content)
