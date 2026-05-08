{% meta description="Unresolved run ID reference" /%}

{% run id="step1" bash="echo hello" /%}

This references {% $step2.result %} which doesn't exist.
