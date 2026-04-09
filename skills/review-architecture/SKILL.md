---
name: review-architecture
description: project-specific architectural review skill for validating plans, epics, and issues against the platform platform architecture
---

# Platform Architectural Review Skill

This skill performs architectural validation specific to the platform application marketplace platform. Invoke this skill during planning and grooming workflows to ensure alignment with the platform architecture.

## Platform Business Domain Context

**the platform is an application marketplace where users purchase access to sessions in third-party applications.**

| Concept | Definition | Architectural Concern |
|---------|------------|----------------------|
| **Platform Tokens** | Currency users purchase from the platform | Token accounting, balance management, transaction integrity |
| **Sessions** | Paid access windows into 3rd-party third-party app apps | Session lifecycle, timeout handling, state management |
| **Publishers** | 3rd parties who list apps and set token prices | Publisher onboarding, app registration, pricing rules |
| **Marketplace** | Discovery and launch of application sessions | Search, filtering, recommendations, launch flow |

## Repository Architecture

| Repository | Scope | Architectural Boundaries |
|------------|-------|-------------------------|
| `api-service` | Core business logic | Sessions, tokens, marketplace, publisher APIs |
| `frontend-app` | Frontend marketplace UI | React components, state management, API integration |
| `auth-service` | Platform authentication | Cognito, JWT, permissions (NOT session tokens) |
| `sdk` | Publisher integration SDK | External developer experience, webhooks |
| `project-docs` | Documentation and PRPs | Specs, guides, API reference |
| `e2e-tests` | Playwright E2E testing | Cross-repo integration tests |
| `jwt-demo` | JWT demonstration service | Auth flow testing, token debugging |

## Architectural Review Checklist

### Phase 1: Domain Boundary Validation

> **Skill reference:** [domain-context](.claude/skills/domain-context.skill.md)

**If domain model is available (`TENANT_DOMAIN_PATH` set), load bounded context boundaries from CML:**

```bash
python3 -c "
import json, os
idx = json.load(open(os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))))
for name, ctx in idx['contexts'].items():
    print(f'{name} ({ctx[\"implements\"]}):')
    for r in ctx.get('responsibilities', [])[:3]:
        print(f'  - {r}')
"
```

**Validate against CML model (preferred over hardcoded knowledge below):**
- [ ] Each change maps to a declared bounded context
- [ ] New entities are placed in the correct aggregate per CML
- [ ] Cross-context communication follows declared ContextMap relationships
- [ ] New commands/events follow naming conventions from CML model

**Fallback (if domain model not available):**

**CRITICAL: Session vs Authentication Disambiguation**

```markdown
[ ] Does the change involve "sessions"?
    - Platform login session → belongs in `auth-service`
    - App access session (token-gated) → belongs in `api-service`
    - NEVER mix these concepts in the same component

[ ] Does the change involve "tokens"?
    - JWT auth tokens → `auth-service`
    - SMART marketplace tokens → `api-service`
    - Session access tokens → `api-service`
```

**Repository Assignment Validation:**

```markdown
[ ] Is each task assigned to the correct repository?
[ ] Are cross-repo dependencies explicitly documented?
[ ] Does the change respect existing module boundaries?
[ ] Are shared types/interfaces defined in the correct package?
```

### Phase 2: Token Economy Integrity

**SMART Token Architectural Rules:**

```markdown
[ ] Token balance modifications use atomic transactions
[ ] Token transfers have idempotency keys
[ ] Pricing changes don't affect in-progress sessions
[ ] Token history maintains complete audit trail
[ ] Refund logic handles edge cases (expired sessions, partial use)
```

**Session Token Rules:**

```markdown
[ ] Session tokens have defined expiration
[ ] Session state is recoverable after token refresh
[ ] Token revocation cascades to active sessions
[ ] Session handoff (if applicable) preserves token accounting
```

### Phase 3: Publisher Integration Architecture

**Publisher API Boundaries:**

```markdown
[ ] Publisher-facing APIs are versioned
[ ] Webhook payloads include idempotency information
[ ] SDK changes maintain backward compatibility
[ ] Publisher dashboard changes don't affect marketplace users
[ ] Rate limiting protects both the project and publisher systems
```

**App Registration Flow:**

```markdown
[ ] App metadata validation is comprehensive
[ ] Pricing tiers are validated at registration
[ ] Category/tag assignment follows taxonomy
[ ] App launch URLs are validated and secured
```

### Phase 4: Frontend Architecture (frontend-app)

**Component Architecture:**

```markdown
[ ] New components follow existing patterns (POM for tests)
[ ] State management uses established patterns (context/hooks)
[ ] API calls use centralized client with error handling
[ ] Loading/error states are handled consistently
[ ] Responsive design requirements are addressed
```

**User Flow Validation:**

```markdown
[ ] Authentication flow integrates with auth-service
[ ] Token balance is displayed accurately
[ ] Session launch flow handles all error states
[ ] Publisher content is properly sandboxed
```

### Phase 5: API Architecture (api-service)

**Lambda Handler Patterns:**

```markdown
[ ] Handlers follow single-responsibility principle
[ ] Error responses use standard format
[ ] Input validation happens at handler boundary
[ ] Database operations use connection pooling
[ ] Sensitive data is never logged
```

**Data Model Integrity:**

```markdown
[ ] Schema changes are backward compatible
[ ] Migrations are reversible where possible
[ ] Indexes support expected query patterns
[ ] Foreign key relationships are properly defined
```

### Phase 6: Security Architecture

**Authentication & Authorization:**

```markdown
[ ] All endpoints require appropriate auth
[ ] Role-based access is enforced at API level
[ ] Publisher isolation is maintained
[ ] User data access follows privacy requirements
```

**Data Protection:**

```markdown
[ ] PII is encrypted at rest
[ ] Tokens are never exposed in URLs
[ ] Session data doesn't leak cross-tenant
[ ] Audit logs capture security-relevant events
```

### Phase 7: Cross-Repository Impact

**Dependency Analysis:**

```markdown
[ ] Changes to api-service don't break frontend-app without version bump
[ ] auth-service changes coordinate with dependent repos
[ ] sdk changes include migration guide for publishers
[ ] Shared types are updated atomically across repos
```

**Integration Testing:**

```markdown
[ ] e2e-tests tests cover the changed flows
[ ] Cross-repo integration points have tests
[ ] Mock services accurately represent real behavior
[ ] Test data fixtures are updated if needed
```

## Architectural Red Flags

**Automatic rejection triggers:**

| Red Flag | Why It Fails | Fix Required |
|----------|--------------|--------------|
| Session logic in auth-service | Domain boundary violation | Move to api-service |
| Token accounting without transactions | Data integrity risk | Add atomic operations |
| Direct DB access from frontend-app | Architecture violation | Use API endpoints |
| Publisher data visible to other publishers | Security violation | Add tenant isolation |
| JWT tokens stored in localStorage | Security vulnerability | Use httpOnly cookies |
| Missing idempotency on payment operations | Financial risk | Add idempotency keys |
| Hardcoded environment values | Deployment risk | Use environment config |
| Cross-repo shared state | Coupling violation | Use API contracts |

## Review Output Format

After completing the architectural review, output:

```markdown
## Platform Architectural Review: [ISSUE_KEY or PRP_NAME]

**Review Status:** PASS | FAIL | NEEDS_REVISION

### Domain Boundary Check
- [ ] Session/Auth separation: PASS/FAIL
- [ ] Repository assignment: PASS/FAIL
- [ ] Module boundaries: PASS/FAIL

### Token Economy Check
- [ ] SMART token integrity: PASS/FAIL/N/A
- [ ] Session token handling: PASS/FAIL/N/A

### Publisher Integration Check
- [ ] API versioning: PASS/FAIL/N/A
- [ ] SDK compatibility: PASS/FAIL/N/A

### Security Check
- [ ] Auth requirements: PASS/FAIL
- [ ] Data protection: PASS/FAIL

### Cross-Repo Impact Check
- [ ] Dependency analysis: PASS/FAIL
- [ ] Integration testing: PASS/FAIL/NEEDS_TESTS

### Red Flags Detected
[List any red flags found, or "None"]

### Required Changes
[List required changes before approval, or "None - approved"]

### Recommendations
[Optional improvements that don't block approval]
```

## Integration with Workflow Commands

This skill is invoked by:
- `/plan` - During PRP creation, review architectural alignment
- `/groom` - During issue creation, validate each issue's architecture
- `/validate-prp` - As part of PRP validation
- `/validate-groom` - As part of grooming validation

**Invocation pattern in commands:**

```markdown
## Phase N: Architectural Review

> Skill reference: [review-architecture](.claude/skills/review-architecture.md)

Execute the platform architectural review checklist against:
- The PRP document (for /plan, /validate-prp)
- Each created issue (for /groom, /validate-groom)

**Mandatory output:** Complete the review output format above.

**Blocking conditions:**
- Any FAIL status requires resolution before proceeding
- Red flags must be addressed or explicitly waived with justification
```

## AWS Environment Awareness

**Profile requirements for architectural review:**

| Environment | Profile | When to Consider |
|-------------|---------|------------------|
| `your-dev-profile` | Development | Default for most reviews |
| `your-demo-profile` | Demo | Pre-production architecture validation |
| `your-prod-profile` | Production | Production impact assessment |

**Environment-specific concerns:**

```markdown
[ ] Does the change require infrastructure updates?
[ ] Are there environment-specific configurations needed?
[ ] Is the change safe to deploy incrementally?
[ ] Are rollback procedures defined?
```
