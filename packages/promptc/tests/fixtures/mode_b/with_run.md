{% meta doc_type="command" description="Sample command with run blocks" /%}

{% input name="issue" type="string" required=true /%}
{% output name="STATUS" type="string" /%}

## Phase: Fetch Issue Data

Retrieve the issue details from Jira for {% $inputs.issue %}.

{% run id="issue_data" skill="jira/get_issue" %}
{"issue_key": "{% $inputs.issue %}"}
{% /run %}

## Phase: Process Results

We will process the results.
