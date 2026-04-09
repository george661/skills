<!-- MODEL_TIER: sonnet -->

# /e2e-write <issue-key>

Write a Playwright spec file for the given issue key to `$E2E_REPO/$E2E_TEST_DIR/issues/`.
Open a draft PR in `$E2E_REPO`. Save spec path and draft PR to checkpoint.

**FAIL FAST:** If any required variable is unset, print the variable name and stop.

```
Required: E2E_REPO, E2E_TEST_DIR, E2E_TAG_PREFIX, E2E_JIRA_BASE_URL, E2E_TEST_DATA_INSTRUCTIONS
```

## Step 0: Guard — spec already exists?

Check if `$PROJECT_ROOT/../$E2E_REPO/$E2E_TEST_DIR/issues/$ARGUMENTS.spec.ts` exists.

**If it exists:**
- Search open PRs on `$E2E_REPO` for the issue key to find the draft PR number
- Write to checkpoint: `e2e.spec-path`, `e2e.draft-pr-number`, `e2e.draft-pr-repo: $E2E_REPO`
- Print: "Spec already exists at [path]. Checkpoint updated with existing spec path and PR number."
- **Stop — do not regenerate**

## Step 1: Read test data instructions

Read `$E2E_TEST_DATA_INSTRUCTIONS` (resolving any `$E2E_TEST_DATA_REPO` references in the path).
Understand how credentials and fixtures are loaded in this tenant's E2E tests. This determines
what `loadTestData` or equivalent call to include in the spec.

## Step 2: Fetch issue details

Call `jira/get_issue.ts` for `$ARGUMENTS`. Extract:
- `summary` — one-sentence issue title
- `description` — full description
- `acceptance criteria` — parse from description or custom field

## Step 3: Determine if observable

The issue has observable effects if ANY of the following are true:
- AC mentions something a user "sees", "views", "navigates to", "clicks", "fills in", "submits"
- The issue type is Bug
- The issue description mentions UI, dashboard, page, screen, form, button, table, list, modal
- The issue affects data rendered in the frontend (sessions, balances, listings, profiles, tokens)
- The issue is in a repo listed in `$E2E_FRONTEND_REPOS`

**If NOT observable:**
- Write to checkpoint: `e2e.not-applicable: true`
- Print: "Issue $ARGUMENTS has no observable user-facing effects. Skipping E2E spec."
- **Stop**

## Step 4: Generate spec file

Generate `$E2E_TEST_DIR/issues/$ARGUMENTS.spec.ts` using this exact structure:

```typescript
// Issue: $ARGUMENTS — <summary from Jira>

import { test, expect } from '@playwright/test';
// <import for test data per $E2E_TEST_DATA_INSTRUCTIONS>

test.describe('chromium desktop', {
  tag: ['@$ARGUMENTS', '@regression', '@chromium-desktop']
}, () => {
  test.use({ browserName: 'chromium', viewport: { width: 1280, height: 800 } });

  // One test() block per acceptance criterion:
  test('<AC criterion verbatim>', {
    tag: ['@$ARGUMENTS', '@regression', '@chromium-desktop']
  }, async ({ page }) => {
    test.info().annotations.push(
      { type: 'issue',    description: '$ARGUMENTS' },
      { type: 'jira',     description: '$E2E_JIRA_BASE_URL/browse/$ARGUMENTS' },
      { type: 'viewport', description: 'chromium-desktop 1280x800' }
    );
    // Navigate to the relevant page
    // Assert the CORRECT (expected) behavior — this assertion FAILS now because the feature is not yet implemented
    // Example: await expect(page.locator('[data-testid="feature-element"]')).toBeVisible();
  });
});

test.describe('safari mobile', {
  tag: ['@$ARGUMENTS', '@regression', '@webkit-mobile']
}, () => {
  test.use({ browserName: 'webkit', viewport: { width: 390, height: 844 } });

  test('<AC criterion verbatim>', {
    tag: ['@$ARGUMENTS', '@regression', '@webkit-mobile']
  }, async ({ page }) => {
    test.info().annotations.push(
      { type: 'issue',    description: '$ARGUMENTS' },
      { type: 'jira',     description: '$E2E_JIRA_BASE_URL/browse/$ARGUMENTS' },
      { type: 'viewport', description: 'webkit-mobile 390x844' }
    );
    // Same assertions as chromium block
  });
});
```

**Key authoring rules:**
- Each `test()` asserts the **correct, expected behavior** — not the broken state
- The test must fail RIGHT NOW because the feature does not yet exist
- For bugs: assert the state that should exist after the fix (not the broken state)
- Use `data-testid` selectors where available; fall back to ARIA roles
- Do NOT use CSS selectors or positional locators
- Each acceptance criterion = one `test()` block in each describe

## Step 5: Commit spec to E2E repo and open draft PR

```bash
# From the E2E repo dir
cd $PROJECT_ROOT/../$E2E_REPO
git checkout -b $ARGUMENTS-e2e-spec
git add $E2E_TEST_DIR/issues/$ARGUMENTS.spec.ts
git commit -m "test($ARGUMENTS): add E2E spec for $ARGUMENTS"
```

Create a **draft PR** using `bitbucket/create_pull_request.ts` or `github/create_pull_request.ts`
(whichever VCS skill is configured). Title: `test($ARGUMENTS): E2E spec (draft — awaiting GREEN)`.

## Step 6: Save to checkpoint

Write these fields to the issue checkpoint:
- `e2e.spec-path: $E2E_TEST_DIR/issues/$ARGUMENTS.spec.ts`
- `e2e.draft-pr-number: <PR number>`
- `e2e.draft-pr-repo: $E2E_REPO`

Print: "E2E spec written to [$E2E_TEST_DIR/issues/$ARGUMENTS.spec.ts]. Draft PR #[N] opened in $E2E_REPO."
