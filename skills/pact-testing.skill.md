---
name: pact-testing
description: Consumer-driven contract testing with Pact - write, run, fix, and analyze pact tests for service integration verification
---

# Pact Contract Testing Skill

Pact is a consumer-driven contract testing framework that verifies services can communicate correctly without requiring full integration test environments.

## Overview

### What is Pact?

Pact enables **contract testing** - verifying that services (consumer and provider) can talk to each other by:
1. Consumer defines expectations in tests
2. Pact generates contract files (pacts) from test execution
3. Provider verifies it satisfies the contracts

**Analogy**: Testing a smoke alarm by pressing its test button rather than setting your house on fire.

### Core Concepts

| Concept | Definition |
|---------|------------|
| **Consumer** | Service that makes requests (API client) |
| **Provider** | Service that responds to requests (API server) |
| **Pact** | JSON contract file capturing expected interactions |
| **Interaction** | Single request/response pair in a contract |
| **Pact Broker** | Central repository for storing and sharing pacts |

## Package Installation

```bash
# Node.js - Primary package
npm install --save-dev @pact-foundation/pact

# For provider verification
npm install --save-dev @pact-foundation/pact-core
```

## Writing Consumer Tests

### Basic Structure

```typescript
import { PactV3, MatchersV3 } from '@pact-foundation/pact';
import path from 'path';

const { like, eachLike, string, integer, boolean, datetime } = MatchersV3;

const provider = new PactV3({
  consumer: 'MyConsumer',
  provider: 'MyProvider',
  dir: path.resolve(process.cwd(), 'pacts'),
  logLevel: 'warn',
});

describe('My API Consumer', () => {
  it('gets a user by ID', async () => {
    // Arrange: Define expected interaction
    provider
      .given('a user with ID 1 exists')
      .uponReceiving('a request for user 1')
      .withRequest({
        method: 'GET',
        path: '/api/users/1',
        headers: {
          Accept: 'application/json',
        },
      })
      .willRespondWith({
        status: 200,
        headers: {
          'Content-Type': 'application/json',
        },
        body: {
          id: integer(1),
          name: string('John Doe'),
          email: string('john@example.com'),
          active: boolean(true),
        },
      });

    // Act & Assert: Execute against mock server
    await provider.executeTest(async (mockServer) => {
      const response = await fetch(`${mockServer.url}/api/users/1`, {
        headers: { Accept: 'application/json' },
      });

      const user = await response.json();

      expect(response.status).toBe(200);
      expect(user.id).toBe(1);
      expect(user.name).toBeDefined();
    });
  });
});
```

### Common Matchers

```typescript
import { MatchersV3 } from '@pact-foundation/pact';

const {
  like,           // Match by type, use example for contract
  eachLike,       // Array where each element matches type
  string,         // String matcher
  integer,        // Integer matcher
  decimal,        // Decimal/float matcher
  boolean,        // Boolean matcher
  datetime,       // DateTime with format
  regex,          // Regex pattern
  uuid,           // UUID format
  email,          // Email format
  nullValue,      // Explicit null
  fromProviderState, // Value from provider state
} = MatchersV3;

// Example: Complex response matching
const responseBody = {
  id: uuid(),
  name: string('Example'),
  price: decimal(99.99),
  tags: eachLike('tag'),
  metadata: like({
    created: datetime("yyyy-MM-dd'T'HH:mm:ss.SSSXXX"),
    version: integer(1),
  }),
  status: regex('active|inactive', 'active'),
};
```

### Testing Error Responses

```typescript
it('returns 404 for non-existent user', async () => {
  provider
    .given('no user with ID 999 exists')
    .uponReceiving('a request for non-existent user')
    .withRequest({
      method: 'GET',
      path: '/api/users/999',
    })
    .willRespondWith({
      status: 404,
      body: {
        error: string('Not Found'),
        message: string('User not found'),
      },
    });

  await provider.executeTest(async (mockServer) => {
    const response = await fetch(`${mockServer.url}/api/users/999`);
    expect(response.status).toBe(404);
  });
});
```

## Writing Provider Verification Tests

### Basic Provider Verification

```typescript
import { Verifier } from '@pact-foundation/pact';
import path from 'path';

describe('Provider Verification', () => {
  it('validates the provider against consumer contracts', async () => {
    const verifier = new Verifier({
      providerBaseUrl: 'http://localhost:3000',
      pactUrls: [
        path.resolve(process.cwd(), 'pacts', 'MyConsumer-MyProvider.json'),
      ],
      // Optional: Provider states handler
      stateHandlers: {
        'a user with ID 1 exists': async () => {
          // Setup test data
          await createTestUser({ id: 1, name: 'John Doe' });
        },
        'no user with ID 999 exists': async () => {
          // Ensure user doesn't exist
          await deleteTestUser(999);
        },
      },
    });

    await verifier.verifyProvider();
  });
});
```

### Using Pact Broker

```typescript
const verifier = new Verifier({
  providerBaseUrl: 'http://localhost:3000',
  pactBrokerUrl: 'https://your-broker.pactflow.io',
  pactBrokerToken: process.env.PACT_BROKER_TOKEN,
  provider: 'MyProvider',
  publishVerificationResult: true,
  providerVersion: process.env.GIT_COMMIT || '1.0.0',
  providerVersionBranch: process.env.GIT_BRANCH || 'main',
  consumerVersionSelectors: [
    { mainBranch: true },
    { deployedOrReleased: true },
  ],
});
```

## CLI Commands

### Running Consumer Tests

```bash
# Run pact tests (generates pact files)
npm test -- --grep "Pact"

# Or with jest
npx jest --testPathPattern=pact

# Pact files are generated in ./pacts directory
```

### Verifying Provider

```bash
# Verify against local pact files
npx pact-provider-verifier \
  --provider-base-url=http://localhost:3000 \
  --pact-urls=./pacts/Consumer-Provider.json

# Verify against Pact Broker
npx pact-provider-verifier \
  --provider-base-url=http://localhost:3000 \
  --pact-broker-base-url=https://your-broker.pactflow.io \
  --pact-broker-token=$PACT_BROKER_TOKEN \
  --provider=MyProvider
```

### Publishing Pacts

```bash
# Publish to Pact Broker
npx pact-broker publish ./pacts \
  --consumer-app-version=$(git rev-parse HEAD) \
  --branch=$(git rev-parse --abbrev-ref HEAD) \
  --broker-base-url=https://your-broker.pactflow.io \
  --broker-token=$PACT_BROKER_TOKEN
```

### Can-I-Deploy Check

```bash
# Check if safe to deploy
npx pact-broker can-i-deploy \
  --pacticipant=MyService \
  --version=$(git rev-parse HEAD) \
  --to-environment=production \
  --broker-base-url=https://your-broker.pactflow.io \
  --broker-token=$PACT_BROKER_TOKEN
```

## Project Structure

```
project/
├── src/
│   └── api/
│       └── userClient.ts        # Consumer API client
├── pacts/                       # Generated pact files
│   └── Consumer-Provider.json
├── test/
│   ├── pact/
│   │   ├── consumer/            # Consumer contract tests
│   │   │   └── user.pact.spec.ts
│   │   └── provider/            # Provider verification tests
│   │       └── verify.spec.ts
│   └── fixtures/
│       └── pact-states.ts       # Provider state handlers
├── pact-config.ts               # Shared Pact configuration
└── package.json
```

## Debugging Failed Pacts

### Common Failure Patterns

| Error | Cause | Fix |
|-------|-------|-----|
| `Missing interaction` | Provider doesn't handle expected request | Add endpoint or fix route |
| `Response mismatch` | Response structure differs from contract | Update response format |
| `State handler error` | Provider state setup failed | Fix state handler function |
| `Connection refused` | Provider not running | Start provider before verification |

### Debugging Commands

```bash
# Verbose output
PACT_LOG_LEVEL=debug npm test

# View generated pact file
cat pacts/Consumer-Provider.json | jq .

# List interactions in pact
jq '.interactions[] | {description, request: .request.path}' pacts/Consumer-Provider.json
```

### Reading Pact Files

```json
{
  "consumer": { "name": "MyConsumer" },
  "provider": { "name": "MyProvider" },
  "interactions": [
    {
      "description": "a request for user 1",
      "providerState": "a user with ID 1 exists",
      "request": {
        "method": "GET",
        "path": "/api/users/1"
      },
      "response": {
        "status": 200,
        "body": { "id": 1, "name": "John Doe" }
      }
    }
  ]
}
```

## Best Practices

### DO

- **Test actual consumer needs** - Only test interactions your consumer actually uses
- **Use matchers** - Prefer type matchers over exact values for flexibility
- **Meaningful provider states** - Clear descriptions of test data setup
- **Version pacts** - Tie pacts to git commits for traceability
- **Run in CI** - Consumer tests generate pacts, provider verifies on every build

### DON'T

- **Test every endpoint** - Only what consumer needs
- **Hardcode values** - Use matchers for response flexibility
- **Skip provider states** - They ensure reproducible test data
- **Share pacts manually** - Use Pact Broker for collaboration
- **Ignore verification failures** - They indicate real integration bugs

## Integration with the platform Workflow

### When to Write Pact Tests

| Scenario | Use Pact? |
|----------|-----------|
| New API consumer endpoint | YES - Write consumer test first |
| Modifying API response structure | YES - Update consumer expectations |
| Adding new provider endpoint | Only if consumer will use it |
| Internal refactoring | NO - Pact tests external contracts |

### Memory Patterns

```javascript
// Store pact test context
// Session ID pattern: {issue-key-lowercase}-pact-test
const issueKey = "PROJ-123"; // Replace with actual issue key
mcp__agentdb__reflexion_store_episode({
  session_id: `${issueKey.toLowerCase()}-pact-test`,
  task: `pact-consumer-test-${issueKey}`,
  reward: 1.0,
  success: true,
  input: "Write consumer pact test for user API",
  output: "Created pacts/GwSpa-GwApi.json with 3 interactions"
})
```

### CI Pipeline Integration

```yaml
# In bitbucket-pipelines.yml
steps:
  - step:
      name: Consumer Pact Tests
      script:
        - npm test -- --grep "pact"
        - npx pact-broker publish ./pacts \
            --consumer-app-version=$BITBUCKET_COMMIT \
            --branch=$BITBUCKET_BRANCH

  - step:
      name: Provider Verification
      script:
        - npm run start:test &
        - npx pact-provider-verifier \
            --provider-base-url=http://localhost:3000 \
            --pact-broker-base-url=$PACT_BROKER_URL
```

## Troubleshooting

### Test Hangs

```typescript
// Ensure mock server is properly cleaned up
afterAll(async () => {
  await provider.finalize();
});
```

### Mock Server Port Conflicts

```typescript
const provider = new PactV3({
  consumer: 'MyConsumer',
  provider: 'MyProvider',
  port: 0, // Let Pact choose available port
});
```

### Provider State Not Applied

```typescript
// Ensure state handlers return promises
stateHandlers: {
  'user exists': async () => {
    await db.createUser({ id: 1 }); // Must await!
  },
}
```
