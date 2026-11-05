---
name: attention-metrics
description: View and analyze Attention Guard metrics.
---
# Attention Guard Metrics

To view metrics, use the `run_command` tool to execute:
`rtk python3 $(ls ~/.gemini/config/plugins/*/scripts/diagnostics.py 2>/dev/null | head -n 1) --metrics --json`
