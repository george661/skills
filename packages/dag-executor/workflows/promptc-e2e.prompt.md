{% meta tier="contract" description="E2E test prompt for promptc integration" /%}

{% run id="timestamp" bash="date -u +%Y-%m-%d" /%}

{% input name="task" type="string" required=true /%}

# Task Review

This is a synthetic integration test. You are reviewing the following task description and must always produce a verdict.

**Task:** {% $inputs.task %}
**Date:** $timestamp

**Review Guidelines:**
- If the task description is non-empty and describes a concrete action, respond with APPROVED
- If the task description is empty or meaningless, respond with REJECTED
- Always emit both VERDICT and SUMMARY, regardless of whether you have questions

You MUST respond in the following format:

```
verdict: APPROVED
summary: Your one-line summary here
```

Or:

```
verdict: REJECTED
summary: Your one-line summary here
```

The verdict must be exactly one of: APPROVED or REJECTED.
The summary should be a brief one-line explanation.

{% output name="verdict" type="enum" values=["APPROVED", "REJECTED"] /%}
{% output name="summary" type="string" /%}
