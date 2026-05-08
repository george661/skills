{% meta doc_type="command" description="Command with unbound run refs" /%}

{% input name="issue" type="string" required=true /%}
{% output name="STATUS" type="string" /%}

The status is: {% $issue_data.status %}
The summary is: {% $issue_data.summary %}
