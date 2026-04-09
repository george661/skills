---
name: hurl-testing
description: HTTP request testing with Hurl - write, run, fix, and analyze HTTP tests using plain text format
---

# Hurl HTTP Testing Skill

Hurl is a command line tool for running HTTP requests defined in plain text format. It's ideal for API testing, integration testing, and CI/CD pipeline validation.

## Overview

### What is Hurl?

Hurl enables **HTTP testing** using a simple, readable text format:
1. Define requests in `.hurl` files
2. Add assertions to validate responses
3. Chain requests with captured values
4. Run in CI/CD for automated testing

**Key Features**:
- Plain text format (readable, version-controllable)
- Request chaining with value capture
- Rich assertions (status, headers, body, performance)
- Multiple report formats (HTML, JSON, JUnit, TAP)

### Core Concepts

| Concept | Definition |
|---------|------------|
| **Entry** | Single HTTP request with optional response assertions |
| **Captures** | Extract values from responses for use in subsequent requests |
| **Asserts** | Validate response properties (status, headers, body) |
| **Options** | Request-specific configuration (timeouts, retries, auth) |

## Installation

```bash
# macOS
brew install hurl

# Ubuntu/Debian
curl -LO https://github.com/Orange-OpenSource/hurl/releases/download/5.0.1/hurl_5.0.1_amd64.deb
sudo dpkg -i hurl_5.0.1_amd64.deb

# npm (via wrapper)
npm install -g @anthropic-ai/hurl

# Docker
docker run --rm -v $(pwd):/data ghcr.io/orange-opensource/hurl:latest test.hurl
```

## Writing Hurl Tests

### Basic Request

```hurl
# Simple GET request
GET http://localhost:3000/api/health

HTTP 200
[Asserts]
header "Content-Type" == "application/json"
jsonpath "$.status" == "healthy"
```

### Request with Headers and Body

```hurl
# POST request with JSON body
POST http://localhost:3000/api/users
Content-Type: application/json
Authorization: Bearer {{auth_token}}
{
  "name": "John Doe",
  "email": "john@example.com"
}

HTTP 201
[Asserts]
jsonpath "$.id" exists
jsonpath "$.name" == "John Doe"
jsonpath "$.email" == "john@example.com"

[Captures]
user_id: jsonpath "$.id"
```

### Chaining Requests

```hurl
# Step 1: Login
POST http://localhost:3000/api/auth/login
Content-Type: application/json
{
  "email": "admin@example.com",
  "password": "secret123"
}

HTTP 200
[Captures]
auth_token: jsonpath "$.token"

# Step 2: Use token in subsequent request
GET http://localhost:3000/api/users/me
Authorization: Bearer {{auth_token}}

HTTP 200
[Asserts]
jsonpath "$.email" == "admin@example.com"

# Step 3: Create resource
POST http://localhost:3000/api/resources
Authorization: Bearer {{auth_token}}
Content-Type: application/json
{
  "name": "Test Resource"
}

HTTP 201
[Captures]
resource_id: jsonpath "$.id"

# Step 4: Verify resource exists
GET http://localhost:3000/api/resources/{{resource_id}}
Authorization: Bearer {{auth_token}}

HTTP 200
[Asserts]
jsonpath "$.name" == "Test Resource"
```

### Assertions

```hurl
GET http://localhost:3000/api/items

HTTP 200
[Asserts]
# Status assertions
status == 200

# Header assertions
header "Content-Type" contains "application/json"
header "X-Request-Id" exists
header "Cache-Control" matches "max-age=\\d+"

# Body assertions - JSONPath
jsonpath "$.items" count == 10
jsonpath "$.items[0].id" exists
jsonpath "$.items[0].name" isString
jsonpath "$.items[0].price" >= 0
jsonpath "$.total" isInteger

# Body assertions - XPath (for XML/HTML)
xpath "//title" == "Page Title"
xpath "count(//div[@class='item'])" == 10

# Body assertions - Regex
body matches ".*success.*"

# Performance assertions
duration < 1000  # Response under 1 second

# Certificate assertions
certificate "Subject" contains "example.com"
certificate "Expire-Date" daysAfterNow > 30
```

### Using Variables

```hurl
# Variables can be set via CLI, environment, or captures
GET http://localhost:3000/api/users/{{user_id}}
Authorization: Bearer {{API_TOKEN}}

HTTP 200
```

### Form Data

```hurl
# URL-encoded form
POST http://localhost:3000/api/login
Content-Type: application/x-www-form-urlencoded
username=john&password=secret

HTTP 200

# Multipart form with file upload
POST http://localhost:3000/api/upload
[MultipartFormData]
file: file,avatar.png;
description: Profile photo

HTTP 201
```

### Testing Error Responses

```hurl
# Test 400 Bad Request
POST http://localhost:3000/api/users
Content-Type: application/json
{
  "email": "invalid-email"
}

HTTP 400
[Asserts]
jsonpath "$.error" exists
jsonpath "$.message" contains "email"

# Test 401 Unauthorized
GET http://localhost:3000/api/protected

HTTP 401

# Test 404 Not Found
GET http://localhost:3000/api/users/nonexistent

HTTP 404
[Asserts]
jsonpath "$.error" == "Not Found"
```

### Request Options

```hurl
# Per-request options
GET http://localhost:3000/api/slow-endpoint
[Options]
retry: 3
retry-interval: 1000
delay: 500
connect-timeout: 5000
max-time: 30000

HTTP 200

# Skip SSL verification (testing only!)
GET https://self-signed.example.com/api
[Options]
insecure: true

HTTP 200

# Use specific HTTP version
GET http://localhost:3000/api
[Options]
http2: true

HTTP 200
```

## CLI Commands

### Running Tests

```bash
# Run single file
hurl test.hurl

# Run multiple files
hurl tests/*.hurl

# Run with variables
hurl --variable user_id=123 --variable API_TOKEN=xxx test.hurl

# Run with variables file
hurl --variables-file vars.env test.hurl

# Test mode (summary output)
hurl --test tests/*.hurl

# Verbose output
hurl --verbose test.hurl
hurl --very-verbose test.hurl
```

### Variable Files

```properties
# vars.env
API_TOKEN=your-token-here
BASE_URL=http://localhost:3000
USER_ID=123
```

```bash
hurl --variables-file vars.env test.hurl
```

### Generating Reports

```bash
# HTML report
hurl --test --report-html ./reports tests/*.hurl

# JSON report
hurl --test --report-json ./reports tests/*.hurl

# JUnit report (for CI)
hurl --test --report-junit report.xml tests/*.hurl

# TAP report
hurl --test --report-tap report.tap tests/*.hurl
```

### Other Useful Options

```bash
# Ignore asserts (just check connectivity)
hurl --ignore-asserts test.hurl

# Output response body only
hurl --no-output test.hurl

# Save response to file
hurl --output response.json test.hurl

# Use proxy
hurl --proxy http://proxy:8080 test.hurl

# Retry on failure
hurl --retry 3 --retry-interval 1000 test.hurl

# Parallel execution (default in test mode)
hurl --test --jobs 4 tests/*.hurl

# Sequential execution
hurl --test --jobs 1 tests/*.hurl

# Include cookies
hurl --cookie cookies.txt test.hurl
hurl --cookie-jar cookies.txt test.hurl

# Set timeout
hurl --connect-timeout 5000 --max-time 30000 test.hurl
```

## Project Structure

```
project/
├── src/
│   └── api/
├── hurl/                        # Hurl test files
│   ├── smoke/                   # Quick smoke tests
│   │   ├── health.hurl
│   │   └── auth.hurl
│   ├── integration/             # Full integration tests
│   │   ├── users.hurl
│   │   ├── orders.hurl
│   │   └── workflows.hurl
│   ├── regression/              # Regression tests
│   │   └── bug-fixes.hurl
│   └── load/                    # Performance tests
│       └── stress.hurl
├── hurl/vars/                   # Variable files
│   ├── local.env
│   ├── staging.env
│   └── production.env
├── reports/                     # Generated reports
│   ├── html/
│   └── junit/
└── package.json
```

## Debugging Failed Tests

### Common Failure Patterns

| Error | Cause | Fix |
|-------|-------|-----|
| `Connection refused` | Server not running | Start server before tests |
| `Timeout` | Slow response | Increase `max-time` option |
| `Assert failure: jsonpath` | Response structure changed | Update JSONPath assertion |
| `Variable not found` | Missing variable | Set via `--variable` or env |
| `SSL certificate error` | Self-signed cert | Use `insecure: true` option |

### Debugging Commands

```bash
# Show full request/response details
hurl --very-verbose test.hurl

# Show just response headers
hurl --include test.hurl

# Output response body to file for inspection
hurl --output response.json test.hurl
cat response.json | jq .

# Test with curl equivalent
hurl --curl test.hurl  # Outputs curl commands
```

### Reading Hurl Output

```
tests/api.hurl: Running [1/3]
tests/api.hurl: Success (1 request(s) in 120 ms)
tests/users.hurl: Running [2/3]
tests/users.hurl: Success (5 request(s) in 890 ms)
tests/orders.hurl: Running [3/3]
error: Assert failure
  --> tests/orders.hurl:15:1
   |
15 | jsonpath "$.status" == "completed"
   |   actual:   string <pending>
   |   expected: string <completed>
   |
```

## Best Practices

### DO

- **Organize by feature** - Group related tests in files by feature
- **Use variables** - Keep environment-specific values external
- **Chain appropriately** - Capture IDs/tokens for subsequent requests
- **Test error cases** - Include 4xx/5xx response tests
- **Add performance assertions** - Validate response times
- **Use descriptive comments** - Document complex test scenarios

### DON'T

- **Hardcode secrets** - Use environment variables or secret files
- **Skip assertions** - Every request should validate something
- **Ignore test failures** - Fix or update tests, don't disable
- **Over-chain** - Split very long chains into separate files
- **Forget cleanup** - Delete test data after creation tests

## Integration with the platform Workflow

### When to Write Hurl Tests

| Scenario | Use Hurl? |
|----------|-----------|
| API smoke tests | YES - Quick health/connectivity checks |
| API integration tests | YES - Full request/response validation |
| Auth flow testing | YES - Login/token/protected resource chain |
| UI testing | NO - Use Playwright/Cypress instead |
| Unit testing | NO - Use Jest/Vitest instead |

### Memory Patterns

```javascript
// Store Hurl test context
// Session ID pattern: {issue-key-lowercase}-hurl-test
const issueKey = "PROJ-123"; // Replace with actual issue key
mcp__agentdb__reflexion_store_episode({
  session_id: `${issueKey.toLowerCase()}-hurl-test`,
  task: `hurl-integration-test-${issueKey}`,
  reward: 1.0,
  success: true,
  input: "Write Hurl tests for user API endpoints",
  output: "Created hurl/integration/users.hurl with 8 tests, all passing"
})
```

### CI Pipeline Integration

```yaml
# In bitbucket-pipelines.yml
steps:
  - step:
      name: API Tests (Hurl)
      script:
        - npm run start:test &
        - sleep 5  # Wait for server
        - hurl --test --report-junit report.xml hurl/**/*.hurl
      artifacts:
        - report.xml
```

### NPM Scripts

```json
{
  "scripts": {
    "test:hurl": "hurl --test hurl/**/*.hurl",
    "test:hurl:smoke": "hurl --test hurl/smoke/*.hurl",
    "test:hurl:integration": "hurl --test hurl/integration/*.hurl",
    "test:hurl:report": "hurl --test --report-html reports/hurl hurl/**/*.hurl",
    "test:hurl:verbose": "hurl --very-verbose hurl/**/*.hurl",
    "test:hurl:local": "hurl --variables-file hurl/vars/local.env --test hurl/**/*.hurl"
  }
}
```

## Example Test Files

### Health Check (smoke/health.hurl)

```hurl
# Health check endpoint
GET {{BASE_URL}}/api/health

HTTP 200
[Asserts]
jsonpath "$.status" == "healthy"
jsonpath "$.version" exists
duration < 500
```

### Authentication Flow (integration/auth.hurl)

```hurl
# Step 1: Register new user
POST {{BASE_URL}}/api/auth/register
Content-Type: application/json
{
  "email": "test-{{timestamp}}@example.com",
  "password": "Test123!",
  "name": "Test User"
}

HTTP 201
[Captures]
user_email: jsonpath "$.email"

# Step 2: Login
POST {{BASE_URL}}/api/auth/login
Content-Type: application/json
{
  "email": "{{user_email}}",
  "password": "Test123!"
}

HTTP 200
[Asserts]
jsonpath "$.token" exists
jsonpath "$.expiresIn" > 0

[Captures]
auth_token: jsonpath "$.token"

# Step 3: Access protected resource
GET {{BASE_URL}}/api/users/me
Authorization: Bearer {{auth_token}}

HTTP 200
[Asserts]
jsonpath "$.email" == "{{user_email}}"

# Step 4: Logout
POST {{BASE_URL}}/api/auth/logout
Authorization: Bearer {{auth_token}}

HTTP 200

# Step 5: Verify token invalidated
GET {{BASE_URL}}/api/users/me
Authorization: Bearer {{auth_token}}

HTTP 401
```

### CRUD Operations (integration/users.hurl)

```hurl
# List users (empty initially)
GET {{BASE_URL}}/api/users
Authorization: Bearer {{admin_token}}

HTTP 200
[Asserts]
jsonpath "$.items" isCollection

# Create user
POST {{BASE_URL}}/api/users
Authorization: Bearer {{admin_token}}
Content-Type: application/json
{
  "name": "New User",
  "email": "new@example.com"
}

HTTP 201
[Captures]
new_user_id: jsonpath "$.id"

[Asserts]
jsonpath "$.name" == "New User"

# Get created user
GET {{BASE_URL}}/api/users/{{new_user_id}}
Authorization: Bearer {{admin_token}}

HTTP 200
[Asserts]
jsonpath "$.id" == "{{new_user_id}}"
jsonpath "$.name" == "New User"

# Update user
PATCH {{BASE_URL}}/api/users/{{new_user_id}}
Authorization: Bearer {{admin_token}}
Content-Type: application/json
{
  "name": "Updated User"
}

HTTP 200
[Asserts]
jsonpath "$.name" == "Updated User"

# Delete user
DELETE {{BASE_URL}}/api/users/{{new_user_id}}
Authorization: Bearer {{admin_token}}

HTTP 204

# Verify deleted
GET {{BASE_URL}}/api/users/{{new_user_id}}
Authorization: Bearer {{admin_token}}

HTTP 404
```

## Troubleshooting

### SSL/TLS Errors

```hurl
# For self-signed certificates in testing
GET https://localhost:3443/api/health
[Options]
insecure: true

HTTP 200
```

### Slow Endpoints

```hurl
GET http://localhost:3000/api/long-operation
[Options]
max-time: 60000
retry: 3
retry-interval: 2000

HTTP 200
```

### Dynamic Timestamps

```bash
# Generate timestamp variable
hurl --variable timestamp=$(date +%s) test.hurl
```

### Base URL Switching

```bash
# Local
hurl --variable BASE_URL=http://localhost:3000 tests/*.hurl

# Staging
hurl --variable BASE_URL=https://staging-api.example.com tests/*.hurl
```
