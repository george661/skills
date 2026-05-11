{% meta
  tier = "reference"
/%}

{% run id="meta" skill="jira/get_issue" capture="json" %}
{"issue_key": "GW-1"}
{% /run %}

Issue status: $meta.status
