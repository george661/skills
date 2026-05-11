{% meta tier="contract" description="E2E test prompt for promptc integration" /%}

{% run id="timestamp" bash="date -u +%Y-%m-%d" /%}

{% input name="task" type="string" required=true /%}

# Task Review

You are reviewing the following task:

**Task:** ${task}
**Date:** ${timestamp}

Please review this task and provide your verdict.

You MUST respond in the following format:

```
VERDICT: APPROVED
SUMMARY: Your one-line summary here
```

Or:

```
VERDICT: REJECTED
SUMMARY: Your one-line summary here
```

The VERDICT must be exactly one of: APPROVED or REJECTED.
The SUMMARY should be a brief one-line explanation.

{% output name="verdict" type="enum" values=["APPROVED", "REJECTED"] pattern="VERDICT: (.+)" /%}
{% output name="summary" type="string" pattern="SUMMARY: (.+)" /%}
