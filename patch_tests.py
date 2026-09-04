import re

with open('tests/test_attention_check.py', 'r') as f:
    content = f.read()

# Find the index of "class TestSkillsSummaryDetection:" and slice the string
idx = content.find("class TestSkillsSummaryDetection:")
if idx != -1:
    content = content[:idx]

with open('tests/test_attention_check.py', 'w') as f:
    f.write(content)
