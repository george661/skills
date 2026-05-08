{% meta description="Unresolved input reference" /%}

{% input name="foo" type="string" /%}

This references {% $inputs.bar %} which doesn't exist.
