---
name: discover-idea-interview
description: >
  Non-technical stakeholder interview protocol for capturing, clarifying, and
  validating a product idea. Eight business-focused questions that surface the
  problem, persona, value, constraints, and success criteria before any
  engineering consideration begins.
---

# Idea Interview Skill

## Purpose

Discovery begins with understanding the problem, not the solution. This interview
surfaces what stakeholders actually need — in their own language — before
any technical or implementation framing is introduced.

**Key rule:** Ask one question at a time. Wait for the answer. Follow up naturally.
Do not present all 8 questions at once.

**Audience:** Product stakeholders, business owners, non-technical users.
Avoid engineering terms (APIs, schemas, migrations, lambdas, etc.)

---

## Before the Interview

Run `discover/platform-context.skill.md` first. This lets you:
- Confirm whether the idea already exists in some form
- Identify related work to reference during the conversation
- Avoid asking questions that the domain model already answers

---

## The 8 Questions

### Q1 — The Problem

> "What problem are you trying to solve? Tell me what's frustrating or missing today."

- Listen for pain points, not feature requests
- If they immediately describe a solution, ask: "What happens when you can't do that today?"
- Document: the friction, the gap, the current workaround

**Watch for:** "We need a button that..." → reframe to "What can't you accomplish today?"

---

### Q2 — Who It's For

> "Who experiences this problem? Is it your customers, your team, partners, or someone else?"

- Identify the primary persona (buyer, analyst, admin, publisher, etc.)
- Ask if there are secondary personas affected differently
- Distinguish: who requests the change vs. who benefits from it

**Personas in this platform:** Marketplace users, organization admins, application publishers,
global admins, platform operators. Match their description to one of these.

---

### Q3 — The Impact

> "How often does this problem happen, and what does it cost when it does?"

- Frequency: daily, weekly, per transaction?
- Cost: lost time, lost revenue, failed sales, support tickets, user complaints?
- Scale: one person, one org, all users?

This becomes the "Reach" and "Impact" in prioritization.

---

### Q4 — What Good Looks Like

> "If this were solved perfectly, what would a user be able to do that they can't do today?"

- Ask for a concrete scenario: "Walk me through what they'd do step by step."
- This becomes the happy path and acceptance criteria
- Keep it outcome-focused, not UI-focused

**Prompt if vague:** "Imagine I'm a user. What would I click or type? What would I see?"

---

### Q5 — Related or Existing Work

> "Have you seen anything similar in our platform, or in another product you use?"

- Check against the platform context loaded in Step 0
- If something similar exists: "Is this the same as [X], or different in some key way?"
- Surfaces: features to extend vs. new capabilities to build
- Prevents: duplicating work or missing existing building blocks

---

### Q6 — Constraints

> "Are there any deadlines, compliance requirements, or things we must avoid?"

- Hard deadlines (demo, contract, regulatory)
- Budget or team constraints (if relevant to scope)
- Things that are off-limits: "We can't change the payment flow" / "Must work for existing users"
- Integration requirements: "It must work with Stripe" / "Must support SSO"

---

### Q7 — Success Criteria

> "How would you know this worked? What would you measure or observe?"

- Quantitative: "X% fewer support tickets", "Y more sessions purchased"
- Qualitative: "Users stop asking us for this", "Sales team can demo without workarounds"
- Avoid: "It looks good" or "Users like it" — push for something observable

---

### Q8 — Dependencies and Risks

> "Is there anything this idea depends on — other features, decisions, or external things — that aren't in place yet?"

- Pending business decisions (pricing, partnerships, contracts)
- Features in flight that this builds on
- External integrations not yet connected
- Things that could change that would invalidate this idea

---

## Synthesizing the Interview

After all 8 questions, summarize back to the stakeholder:

```
Here's what I heard:

**The problem:** [1-2 sentences]
**Who it affects:** [persona(s), frequency]
**What success looks like:** [concrete outcome]
**Key constraints:** [list]
**Related to existing work:** [yes/no + what]
**Open questions:** [anything unresolved]

Does that capture it correctly?
```

Wait for confirmation or correction before proceeding to brief writing.

---

## Interview Output (for session state)

Record answers in this structure for use by `brief-writer.skill.md`:

```json
{
  "problem": "",
  "persona": "",
  "frequency": "",
  "impact": "",
  "happy_path": "",
  "existing_similarity": "",
  "constraints": [],
  "success_criteria": "",
  "dependencies": [],
  "open_questions": []
}
```
