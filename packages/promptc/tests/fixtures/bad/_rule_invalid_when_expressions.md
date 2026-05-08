{% meta description="Invalid when expression" /%}

{% input name="x" type="string" /%}

{% when expr="invalid..syntax" %}
This when has a syntax error.
{% /when %}
