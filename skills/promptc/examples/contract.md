---
description: Example promptc contract for smoke testing validation
model: sonnet
tier: 6
---

# Example Contract

{% input name="topic" type="string" required=true /%}

{% output name="summary" type="string" /%}

Generate a one-sentence summary about {% $inputs.topic %}.
