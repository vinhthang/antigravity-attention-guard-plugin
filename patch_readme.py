with open('README.md', 'r') as f:
    content = f.read()

content = content.replace('Verifies agent output quality. Forces re-reading of all project and global rules if the agent forgets to summarize its work. Max 3 retries to prevent infinite loops.', 'Acts as an invariant refresh. Periodically reminds the primary agent of the core rule: Delegate all execution to subagents. Max 2 retries to prevent infinite loops.')

with open('README.md', 'w') as f:
    f.write(content)
