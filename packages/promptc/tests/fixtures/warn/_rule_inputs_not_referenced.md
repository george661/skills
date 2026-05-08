{% meta description="Input not referenced" /%}

{% input name="used" type="string" /%}
{% input name="unused" type="string" /%}

This references {% $inputs.used %} but not the other one.
