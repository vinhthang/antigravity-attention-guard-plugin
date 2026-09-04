import re

with open('scripts/enforce-delegation.py', 'r') as f:
    content = f.read()

# Add standard tools to allowlist logic
standard_tools = '["view_file", "grep_search", "list_dir", "find_by_name", "search_web", "read_url_content", "default_api:view_file", "default_api:grep_search", "default_api:list_dir", "default_api:find_by_name", "default_api:search_web", "default_api:read_url_content"]'

allow_block = f"""
        # Allow read-only standard tools
        if tool_name in {standard_tools}:
            print(json.dumps({{"decision": "allow"}}))
            return
"""

content = content.replace('        if tool_name == "call_mcp_tool":', allow_block + '\n        if tool_name == "call_mcp_tool":')

with open('scripts/enforce-delegation.py', 'w') as f:
    f.write(content)
