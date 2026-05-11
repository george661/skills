{% meta
  tier = "contract"
  description = "Review a plan"
/%}

{% output name="verdict" type="enum" values=["APPROVED", "REJECTED"] /%}

Review this plan and output your verdict.

Your response must include:
VERDICT: [APPROVED or REJECTED]
