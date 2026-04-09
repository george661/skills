---
description: Triage a INTAKE intake issue - classify, validate, and either promote to the platform backlog or resolve
arguments:
  - name: issue
    description: INTAKE issue key (e.g., INTAKE-123)
    required: true
---

# Triage Intake Issue: $ARGUMENTS.issue

## Overview

This command performs **iterative triage** of issues reported to the INTAKE intake project by:

1. Loading issue context and checking for new reporter activity
2. Classifying the issue type (Bug, Feature Request, Question, Unclear)
3. Gathering evidence via /audit for any URLs provided
4. Making a triage decision (resolve or request more info)
5. Either resolving the issue or posting a friendly follow-up question
6. **For QUESTION types**: Creating annotated screenshots with visual guides when helpful

**Iterative Design**: This command is designed to be run multiple times on the same issue until a final resolution is reached. Each pass is intelligent and self-contained.

## Workflow State Machine

```
┌────────────────────────────────────────────────────────────────────────┐
│                        INTAKE ISSUE LIFECYCLE                            │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│   [To Do] ─────► [In Progress] ─────► [Done]                          │
│      │               │                   │                             │
│      │               │                   ├── PROMOTED (→ PROJ-XXX)       │
│      │               │                   ├── DUPLICATE (→ linked)      │
│      │               │                   ├── CANNOT_REPRODUCE          │
│      │               │                   └── WONT_FIX                  │
│      │               │                                                 │
│      │               └── Multiple /triage passes                       │
│      │                   - Ask questions (friendly)                    │
│      │                   - Run /audit on URLs                          │
│      │                   - Create visual guides for QUESTION types     │
│      │                   - Wait for reporter response                  │
│      │                                                                 │
│      └── First /triage moves to In Progress                           │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

## MANDATORY: Create Phase TodoWrite Items

**BEFORE doing anything else**, create these TodoWrite items:

```typescript
TodoWrite({
  todos: [
    { content: "Phase 0: Load INTAKE issue context and triage history", status: "pending", activeForm: "Loading context" },
    { content: "Phase 1: Check for and analyze reporter responses", status: "pending", activeForm: "Analyzing responses" },
    { content: "Phase 2: Classify issue type (Bug/Feature/Question)", status: "pending", activeForm: "Classifying issue" },
    { content: "Phase 3: Gather evidence and run /audit on URLs", status: "pending", activeForm: "Gathering evidence" },
    { content: "Phase 4: Make triage decision using decision tree", status: "pending", activeForm: "Making decision" },
    { content: "Phase 5: Execute action (resolve or request info)", status: "pending", activeForm: "Executing action" }
  ]
})
```

---

## Phase Gates (CANNOT PROCEED WITHOUT)

| From | To | Gate Requirement |
|------|-----|------------------|
| 0 | 1 | INTAKE issue loaded, triage history retrieved |
| 1 | 2 | Reporter responses analyzed (if any) |
| 2 | 3 | Issue classified with confidence level |
| 3 | 4 | Evidence gathered (audits complete if URLs present) |
| 4 | 5 | Decision made: RESOLVE or NEED_INFO |

---

## Phase 0: Load Context

### 0.1 Validate Issue Exists in INTAKE Project

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "expand": "changelog,renderedFields,comments"}'
```

**Validation:**
- Issue key must start with "${INTAKE_PROJECT}-"
- If issue is in the project project → STOP: "This issue is in the development project. Use /work instead."
- If issue is Done → Report final status and exit

**Extract from issue:**
- Summary (title)
- Description (reporter's original report)
- All comments (including timestamps and authors)
- Status (To Do / In Progress / Done)
- Attachments (screenshots, files)
- Reporter info
- Created date

### 0.2 Search AgentDB for Triage History

```typescript
// REST skill: recall_query
const triageHistory = JSON.parse(await Bash(`npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "$ARGUMENTS.issue triage history classification evidence decisions questions asked", "k": 5}'`));
```

**Determine triage state:**
```javascript
const triageState = {
  isFirstTriage: !hasTriageHistory,
  lastTriageDate: lastTriageTimestamp || null,
  classificiation: priorClassification || null,
  questionsAsked: priorQuestionsAsked || [],
  evidenceCollected: priorEvidence || [],
  auditResults: priorAuditResults || []
};
```

### 0.3 Check Issue Status and Transition if Needed

```bash
# If first triage and status is "To Do", transition to "In Progress"
# First, list available transitions:
npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.issue"}'

# Then transition the issue:
npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<in-progress-transition-id>", "comment": "Triage started. Analyzing issue...", "notifyUsers": false}'
```

---

## Phase 1: Analyze Reporter Responses

### 1.1 Identify New Comments Since Last Triage

```javascript
// Filter comments to find those from reporter after our last triage comment
const lastTriageComment = comments
  .filter(c => c.body.includes("[Triage]") || c.author.isBot)
  .sort((a, b) => new Date(b.created) - new Date(a.created))[0];

const newReporterComments = comments.filter(c =>
  !c.author.isBot &&
  new Date(c.created) > new Date(lastTriageComment?.created || 0)
);

const hasNewResponse = newReporterComments.length > 0;
```

### 1.2 Extract Information from Responses

If reporter has responded, extract:
- Answers to specific questions we asked
- New URLs provided
- Additional context or clarification
- Screenshots or attachments added

```javascript
const newInfo = {
  hasResponse: hasNewResponse,
  responseContent: newReporterComments.map(c => c.body).join('\n'),
  newUrls: extractUrls(newReporterComments),
  answeredQuestions: matchAnswersToQuestions(
    triageState.questionsAsked,
    newReporterComments
  )
};
```

### 1.3 Update Triage Context

```javascript
const updatedContext = {
  ...triageState,
  reporterResponses: [
    ...triageState.reporterResponses || [],
    ...newReporterComments
  ],
  allUrls: [...new Set([
    ...triageState.allUrls || [],
    ...newInfo.newUrls
  ])]
};
```

---

## Phase 2: Classify Issue

### 2.1 Classification Decision Tree

Apply the following classification logic:

```javascript
function classifyIssue(description, comments) {
  const fullText = [description, ...comments.map(c => c.body)].join(' ').toLowerCase();

  // BUG indicators
  const bugKeywords = [
    'error', 'broken', 'crash', 'doesn\'t work', 'not working',
    'bug', 'issue', 'problem', 'fail', 'exception', 'wrong',
    '500', '404', '403', 'undefined', 'null'
  ];

  // FEATURE REQUEST indicators
  const featureKeywords = [
    'would be nice', 'could you add', 'feature request',
    'can we have', 'suggestion', 'enhancement', 'improve',
    'new feature', 'add support for', 'it would be great'
  ];

  // QUESTION indicators
  const questionKeywords = [
    'how do i', 'how can i', 'is it possible', 'can i',
    'what is', 'where is', 'why does', 'when will',
    'documentation', 'help with'
  ];

  const scores = {
    BUG: bugKeywords.filter(k => fullText.includes(k)).length,
    FEATURE: featureKeywords.filter(k => fullText.includes(k)).length,
    QUESTION: questionKeywords.filter(k => fullText.includes(k)).length
  };

  const maxScore = Math.max(...Object.values(scores));
  const classification = Object.entries(scores)
    .find(([_, score]) => score === maxScore)?.[0] || 'UNCLEAR';

  const confidence = maxScore >= 3 ? 'HIGH' : maxScore >= 1 ? 'MEDIUM' : 'LOW';

  return { classification, confidence, scores };
}
```

### 2.2 Handle Unclear Classification

If confidence is LOW or classification is UNCLEAR:
- Check if we've already asked for clarification
- If not, prepare clarification question
- If we have asked and still unclear, use best guess

```javascript
if (classification.confidence === 'LOW' && !triageState.askedForClassification) {
  // Will ask clarifying question in Phase 5
  pendingQuestions.push({
    type: 'CLASSIFICATION',
    question: "Could you help me understand - are you reporting a problem with something that isn't working correctly, or requesting a new feature/improvement?"
  });
}
```

### 2.3 Record Classification

```javascript
const issueClassification = {
  type: classification.classification, // BUG | FEATURE | QUESTION | UNCLEAR
  confidence: classification.confidence, // HIGH | MEDIUM | LOW
  reasoning: `Matched ${classification.scores[classification.classification]} keywords`,
  timestamp: new Date().toISOString()
};
```

---

## Phase 3: Gather Evidence

### 3.1 Extract URLs for Auditing

```javascript
const urlRegex = /https?:\/\/[^\s<>"{}|\\^`\[\]]+/g;
const allUrls = [
  ...issue.description.match(urlRegex) || [],
  ...issue.comments.flatMap(c => c.body.match(urlRegex) || [])
];

// Filter to relevant URLs (likely the project deployment URLs)
const auditableUrls = allUrls.filter(url =>
  url.includes('cloudfront.net') ||
  url.includes('platform.example.com') ||
  url.includes('localhost')
);
```

### 3.2 Run /audit on Each URL

**For each auditable URL not already audited:**

```typescript
// Use Skill tool to invoke /audit
for (const url of auditableUrls) {
  if (!triageState.auditResults?.find(r => r.url === url)) {
    Skill("audit", url)

    // Store audit result
    auditResults.push({
      url: url,
      auditTimestamp: new Date().toISOString(),
      result: auditOutput
    });
  }
}
```

### 3.3 Search for Potential Duplicates

```bash
# Search the project for similar issues
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND (summary ~ \"${issueSummaryKeywords}\" OR description ~ \"${issueSummaryKeywords}\") AND status != Done ORDER BY created DESC", "max_results": 5, "fields": ["key", "summary", "status", "resolution"]}'

# Search INTAKE for duplicate reports
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${INTAKE_PROJECT} AND key != $ARGUMENTS.issue AND (summary ~ \"${issueSummaryKeywords}\" OR description ~ \"${issueSummaryKeywords}\") ORDER BY created DESC", "max_results": 5, "fields": ["key", "summary", "status", "resolution"]}'
```

### 3.4 Compile Evidence Summary

```javascript
const evidenceSummary = {
  classification: issueClassification,
  auditResults: auditResults,
  potentialDuplicates: {
    inProject: projectDuplicates,
    inINTAKE: gwhdDuplicates
  },
  urlsProvided: auditableUrls.length > 0,
  screenshotsProvided: issue.attachments.length > 0,
  reproStepsProvided: hasReproductionSteps(issue.description),
  sufficientInfo: evaluateInfoSufficiency()
};
```

---

## Phase 4: Make Triage Decision

### 4.1 Decision Tree Evaluation

```javascript
function makeTriageDecision(context, evidence) {
  const { classification, triageState, newInfo } = context;
  const { auditResults, potentialDuplicates, sufficientInfo } = evidence;

  // Check for clear duplicate
  if (potentialDuplicates.inProject.length > 0) {
    const exactMatch = findExactDuplicate(potentialDuplicates.inProject);
    if (exactMatch) {
      return {
        decision: 'RESOLVE',
        resolution: 'DUPLICATE',
        linkedIssue: exactMatch.key,
        reason: `This appears to be a duplicate of ${exactMatch.key}: ${exactMatch.summary}`
      };
    }
  }

  // Check audit results for reproducibility
  const auditConfirmedIssue = auditResults.some(r =>
    r.result.discrepancies?.length > 0
  );

  // Bug with confirmed issue from audit
  if (classification.type === 'BUG' && auditConfirmedIssue) {
    return {
      decision: 'RESOLVE',
      resolution: 'PROMOTED',
      issueType: 'Bug',
      reason: 'Bug confirmed via /audit - issue reproduced'
    };
  }

  // Bug with sufficient manual evidence
  if (classification.type === 'BUG' && sufficientInfo) {
    return {
      decision: 'RESOLVE',
      resolution: 'PROMOTED',
      issueType: 'Bug',
      reason: 'Bug report has sufficient evidence for development'
    };
  }

  // Feature request with clear description
  if (classification.type === 'FEATURE' && sufficientInfo) {
    return {
      decision: 'RESOLVE',
      resolution: 'PROMOTED',
      issueType: 'Story',
      reason: 'Feature request is clear and actionable'
    };
  }

  // Question - check if we can answer it
  // Consider using Visual Help Guide Subskill for UI-related questions
  if (classification.type === 'QUESTION') {
    return {
      decision: 'RESOLVE',
      resolution: 'QUESTION_ANSWERED',
      reason: 'This is a question, not a bug or feature request',
      useVisualGuide: shouldCreateVisualGuide(context) // See Visual Help Guide Subskill section
    };
  }

  // Not enough info - need to ask reporter
  return {
    decision: 'NEED_INFO',
    missingInfo: identifyMissingInfo(context, evidence),
    reason: 'Need additional information from reporter'
  };
}
```

### 4.2 Identify Missing Information

```javascript
function identifyMissingInfo(context, evidence) {
  const missing = [];

  if (!evidence.urlsProvided && context.classification.type === 'BUG') {
    missing.push({
      type: 'URL',
      question: "Could you provide the URL where you encountered this issue? This will help me verify and reproduce the problem."
    });
  }

  if (!evidence.reproStepsProvided && context.classification.type === 'BUG') {
    missing.push({
      type: 'REPRO_STEPS',
      question: "Could you walk me through the steps you took when you encountered this issue? For example: 1) I went to [page], 2) I clicked [button], 3) I saw [error]."
    });
  }

  if (!evidence.screenshotsProvided && context.classification.type === 'BUG') {
    missing.push({
      type: 'SCREENSHOT',
      question: "If possible, could you attach a screenshot showing the issue? This helps us understand exactly what you're seeing."
    });
  }

  if (context.classification.confidence === 'LOW') {
    missing.push({
      type: 'CLARIFICATION',
      question: "I want to make sure I understand correctly - are you reporting something that isn't working as expected (a bug), or suggesting a new feature or improvement?"
    });
  }

  return missing;
}
```

### 4.3 Record Decision

```javascript
const triageDecision = {
  decision: decisionResult.decision, // RESOLVE | NEED_INFO
  resolution: decisionResult.resolution, // PROMOTED | DUPLICATE | CANNOT_REPRODUCE | WONT_FIX | null
  issueType: decisionResult.issueType, // Bug | Story | null
  linkedIssue: decisionResult.linkedIssue, // existing issue key if duplicate
  reason: decisionResult.reason,
  missingInfo: decisionResult.missingInfo,
  timestamp: new Date().toISOString()
};
```

---

## Phase 5: Execute Action

### 5.1 If Decision is RESOLVE → PROMOTED

**Create new issue in the project project:**

```bash
# Determine issue type based on classification (Bug or Story)
# Create the issue with full description
npx tsx ~/.claude/skills/issues/create_issue.ts '{"project_key": "${PROJECT_KEY}", "summary": "[${gwIssueType}] ${issue.summary}", "issue_type": "${gwIssueType}", "priority": "${priority}", "description": "## Summary\n\n${issue.description}\n\n---\n\n## Source\n\n**Intake Ticket:** [${issue.key}](https://your-org.atlassian.net/browse/${issue.key})\n**Reporter:** ${issue.reporter.displayName}\n**Reported:** ${issue.created}\n\n---\n\n## Triage Summary\n\n**Classification:** ${classification.type} (${classification.confidence} confidence)\n**Decision:** Promoted to development backlog\n\n${auditResultsSection}\n\n---\n\n## Evidence\n\n${formattedEvidence}\n\n---\n\n## Reproduction Steps\n\n${issue.reproSteps || \"See original ticket for details\"}\n\n---\n\n*Created via /triage from ${issue.key}*", "labels": ["triage-promoted", "source-${issue.key}", "repo-${determinedRepo}"]}'
```

**Link issues bidirectionally:**

```bash
# Add comment to new the project issue linking back
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "${projectIssueKey}", "body": "**Source Ticket:** [${issue.key}](https://your-org.atlassian.net/browse/${issue.key})"}'

# Add comment to INTAKE issue linking to new the project issue
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "[Triage Complete]\n\nThank you for your report! We'\''ve verified this issue and created a development ticket to address it.\n\n**Development Ticket:** [${projectIssueKey}](https://your-org.atlassian.net/browse/${projectIssueKey})\n\nOur team will work on this and the fix will be included in a future release. You can follow the development ticket for updates.\n\nThank you for helping us improve the platform!"}'
```

**Transition INTAKE to Done:**

```bash
npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.issue"}'

npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<done-transition-id>", "comment": "Promoted to the platform development backlog", "notifyUsers": true}'
```

### 5.2 If Decision is RESOLVE → DUPLICATE

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "[Triage Complete]\n\nThank you for your report! After investigation, we found this issue has already been reported.\n\n**Existing Ticket:** [${triageDecision.linkedIssue}](https://your-org.atlassian.net/browse/${triageDecision.linkedIssue})\n\nWe'\''ve linked your report to the existing ticket. You can follow that ticket for updates on when this will be addressed.\n\nThank you for helping us improve the platform!"}'

npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<done-transition-id>", "comment": "Duplicate of ${triageDecision.linkedIssue}", "notifyUsers": true}'
```

### 5.3 If Decision is RESOLVE → CANNOT_REPRODUCE

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "[Triage Update]\n\nThank you for your report. We attempted to reproduce this issue but were unable to observe the behavior you described.\n\n**What we tried:**\n${auditResultsList}\n\n**Could you help us with:**\n1. Are you still experiencing this issue?\n2. What browser and device are you using?\n3. Can you provide any additional details about what you were doing when this occurred?\n\nIf you'\''re still seeing the problem, please reply with any additional information and we'\''ll investigate further.\n\nThank you for your patience!"}'

# Keep in In Progress - waiting for more info
# If no response after reasonable time, can close as cannot reproduce
```

### 5.4 If Decision is RESOLVE → WONT_FIX

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "[Triage Complete]\n\nThank you for your report. After careful consideration, we'\''ve determined that this ${issueTypeDesc} falls outside our current scope.\n\n**Reason:** ${triageDecision.reason}\n\nWe appreciate you taking the time to share your feedback. While we can'\''t address this particular item, we value your input and it helps us understand user needs.\n\nIf you have any questions about this decision, please don'\''t hesitate to ask.\n\nThank you!"}'

npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<done-transition-id>", "comment": "Won'\''t fix - see comment for details", "notifyUsers": true}'
```

### 5.5 If Decision is NEED_INFO

**Post friendly question(s) to reporter:**

```bash
# Build questionText from triageDecision.missingInfo as numbered list
# Then post the comment:
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "[Triage In Progress]\n\nThank you for reporting this! To help us investigate further, could you provide some additional information?\n\n${questionText}\n\nTake your time - just reply to this ticket when you have a chance, and we'\''ll continue investigating.\n\nThanks!"}'

# Stay in In Progress - will continue on next /triage pass
```

### 5.6 Store Triage State in AgentDB

```typescript
// REST skill: reflexion_store_episode
const reward = triageDecision.decision === 'RESOLVE' ? 1.0 : 0.5;
const critique = `Classification: ${issueClassification.type} (${issueClassification.confidence}). Decision: ${triageDecision.decision} - ${triageDecision.resolution || 'NEED_INFO'}`;
Bash(`npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '${JSON.stringify({
  session_id: "triage-$ARGUMENTS.issue",
  task: "Triage INTAKE issue $ARGUMENTS.issue",
  input: JSON.stringify({ issue: issue, priorState: triageState }),
  output: JSON.stringify({ decision: triageDecision, classification: issueClassification, evidence: evidenceSummary, gwIssueCreated: projectIssueKey || null }),
  reward: reward,
  success: true,
  critique: critique
})}'`);
```

---

## Completion Summary

After all phases complete, provide summary:

### If Resolved:

```markdown
## Triage Complete: $ARGUMENTS.issue

**Resolution:** ${triageDecision.resolution}
**Classification:** ${issueClassification.type}

### Quick Links
- INTAKE: https://your-org.atlassian.net/browse/$ARGUMENTS.issue
${projectIssueKey ? `- Project: https://your-org.atlassian.net/browse/${projectIssueKey}` : ''}

### Summary
${triageDecision.reason}

### Evidence Gathered
- URLs audited: ${auditResults.length}
- Screenshots: ${evidence.screenshotsProvided ? 'Yes' : 'No'}
- Reproduction steps: ${evidence.reproStepsProvided ? 'Yes' : 'No'}

### Next Steps
${projectIssueKey ? `- the project issue ${projectIssueKey} is in BACKLOG
- Use \`/work ${projectIssueKey}\` when ready to implement` : '- Issue resolved, no further action needed'}
```

### If Need More Info:

```markdown
## Triage In Progress: $ARGUMENTS.issue

**Status:** Waiting for reporter response
**Classification:** ${issueClassification.type} (${issueClassification.confidence})

### Questions Asked
${triageDecision.missingInfo.map(i => `- ${i.type}: ${i.question}`).join('\n')}

### Next Steps
1. Wait for reporter to respond
2. Run \`/triage $ARGUMENTS.issue\` again after response
3. Will resolve once sufficient information gathered

### Quick Link
- INTAKE: https://your-org.atlassian.net/browse/$ARGUMENTS.issue
```

---

## Visual Help Guide Subskill

When resolving QUESTION-type issues about platform features, create annotated screenshots to help users understand how to use the functionality.

### When to Use This Subskill

Use annotated screenshots when:
- Issue is classified as QUESTION about how to use a feature
- The feature exists and is accessible in the platform
- Visual guidance would significantly help the reporter
- The question involves UI navigation or button locations

### Step 1: Navigate to the Relevant Page

Use Playwright utilities to navigate to the platform:

```bash
# Navigate to the platform (use appropriate environment)
npx tsx ~/.claude/skills/playwright/navigate.ts '{"url": "https://dev.example.com"}'

# Take a snapshot to see current state
npx tsx ~/.claude/skills/playwright/snapshot.ts '{"url": "https://dev.example.com"}'

# If authentication needed, use auth-navigate with test credentials
# Email domain: mail.dev.example.com (e.g., org-admin-001@mail.dev.example.com)
# Password: from test-data/fixtures/e2e/testData.json
npx tsx ~/.claude/skills/playwright/auth-navigate.ts '{"url": "https://dev.example.com", "loginUrl": "https://auth.dev.example.com/login", "ssmPath": "${role.ssmPath}", "awsProfile": "${role.awsProfile}", "role": "${roleName}", "selectors": ${selectorsJson}}'
```

### Step 2: Capture Screenshot

```bash
# Navigate to the specific feature page and capture screenshot
npx tsx ~/.claude/skills/playwright/navigate.ts '{"url": "https://dev.example.com/path/to/feature"}'

# Take snapshot to see page structure
npx tsx ~/.claude/skills/playwright/snapshot.ts '{"url": "https://dev.example.com/path/to/feature"}'

# Save screenshot to temp file
npx tsx ~/.claude/skills/playwright/screenshot.ts '{"url": "https://dev.example.com/path/to/feature", "outputPath": "/tmp/feature-screenshot.png"}'
```

### Step 3: Get Element Coordinates for Annotation

Use the snapshot output to identify element positions. The Playwright snapshot provides element bounding boxes that can be used for annotation without needing to evaluate scripts in the browser.

### Step 4: Annotate with Python/PIL

```python
from PIL import Image, ImageDraw

# Load the screenshot
img = Image.open('/tmp/feature-screenshot.png')
draw = ImageDraw.Draw(img)

# Element coordinates from Playwright snapshot (add padding for visibility)
x, y, width, height = <x>, <y>, <width>, <height>
padding = 8

# Draw red outlined rectangle
outline_color = (255, 0, 0)  # Red
line_width = 4

left = x - padding
top = y - padding
right = x + width + padding
bottom = y + height + padding

# Draw multiple rectangles for thickness
for i in range(line_width):
    draw.rectangle(
        [left - i, top - i, right + i, bottom + i],
        outline=outline_color
    )

# Save annotated image
output_path = '/tmp/feature-annotated.png'
img.save(output_path)
```

### Step 5: Attach to Jira Issue

```bash
# Upload image as attachment using Jira REST API
curl -s -X POST \
  -H "Authorization: Basic $(echo -n "$JIRA_USERNAME:$JIRA_API_TOKEN" | base64)" \
  -H "X-Atlassian-Token: no-check" \
  -F "file=@/tmp/feature-annotated.png" \
  "https://your-org.atlassian.net/rest/api/3/issue/$ARGUMENTS.issue/attachments"
```

### Step 6: Add Instructions Comment

Post a friendly comment with step-by-step instructions referencing the attached screenshot:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "[Update: How to <Action>]\n\nHi <Reporter>,\n\n<Feature> is now available. Here is how to <accomplish task>:\n\n---\n\n**Step-by-Step Instructions:**\n\n1. Sign in to the platform platform\n2. Navigate to **<Section>** > **<Page>** in the sidebar\n3. Look for the <icon description> (highlighted in the attached screenshot)\n4. Click to <action>\n5. <Additional steps as needed>\n\n**See the attached screenshot** (<filename>.png) - the <element> is highlighted with a red box.\n\n---\n\n**Important Notes:**\n- <Permission requirements>\n- <Any caveats or tips>\n\nLet us know if you have any questions.\n\nThank you,\nthe platform Support"}'
```

### Cleanup

```bash
# Remove temporary files
rm /tmp/feature-screenshot.png /tmp/feature-annotated.png
```

### Example: Organization Name Editing

For a question about editing organization names:

1. Navigate to `https://dev.example.com/organization/general`
2. Capture screenshot of the Organization General page
3. Find the edit button coordinates (pencil icon next to org name)
4. Draw red outline around the edit button
5. Attach annotated image to ticket
6. Post instructions explaining:
   - Navigate to Organization > General
   - Click pencil icon next to organization name
   - Enter new name and save

---

## Friendly Response Guidelines

When communicating with reporters, always:

1. **Start with gratitude**: "Thank you for your report!" / "Thanks for the additional info!"
2. **Use plain language**: Avoid technical jargon when possible
3. **Be specific**: Ask one clear question at a time
4. **Set expectations**: Let them know what happens next
5. **Be patient**: Acknowledge that gathering info takes time
6. **End positively**: "Thank you for helping us improve!"

**Example tone:**
> "Thank you for reporting this! To help us investigate, could you share the URL where you saw this issue? This will help us verify and reproduce the problem.
>
> Take your time - just reply when you have a chance!"

---

## Anti-Patterns (AUTOMATIC FAILURE)

- Processing a the project issue instead of INTAKE = FAILURE
- Not checking for reporter responses on follow-up = FAILURE
- Not running /audit on provided URLs = FAILURE
- Creating the project issue without linking back to INTAKE = FAILURE
- Using technical/unfriendly language with reporters = FAILURE
- Closing as CANNOT_REPRODUCE without attempting /audit = FAILURE
- Not transitioning status appropriately = FAILURE
- Not storing triage state for iteration = FAILURE
- Answering UI questions without visual guide when feature exists = MISSED OPPORTUNITY
- Not cleaning up temporary screenshot files = RESOURCE LEAK

---

## Error Handling

- **Issue not found:** Check if key is correct, verify INTAKE project access
- **No transitions available:** Log current status, may already be resolved
- **Audit fails:** Document failure, proceed with available evidence
- **project issue creation fails:** Log error, keep INTAKE in progress
- **Reporter unresponsive:** After 3 follow-ups, consider closing as insufficient info

---

## Pattern Learning Integration

**Triage patterns train for better classification and resolution.**

At phase completion, store the pattern in AgentDB:
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "triage-phase-N", "reward": 0.9, "success": true}'
```

Phase-specific patterns captured:
- `triage-phase-0`: Context loading efficiency
- `triage-phase-1`: Response detection accuracy
- `triage-phase-2`: Classification accuracy
- `triage-phase-3`: Evidence gathering completeness
- `triage-phase-4`: Decision quality
- `triage-phase-5`: Action execution

**Final completion pattern:**
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "workflow-triage-complete", "reward": 0.9, "success": true}'
```

---

**START NOW: Create the TodoWrite items above, then begin Phase 0.**
