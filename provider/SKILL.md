---
name: provider
description: >
  Integrate applications with the platform marketplace as an app
  provider. Uses the Integration Wizard CLI to install the Provider SDK,
  generate framework-specific integration code (React, Vue, Vanilla JS +
  10 backend frameworks), and verify the integration. Uses the Platform MCP
  server to register and publish apps on the marketplace. Use when building
  apps for the platform, integrating with the platform marketplace, or when the user
  mentions the platform, application marketplace, provider SDK, or platform tokens.
license: MIT
metadata:
  author: mission-sciences
  version: "1.0"
compatibility: >
  Requires Node.js 18+. Network access to platform.example.com for MCP
  operations and wizard API. CLI tools work offline for code generation.
---

# Provider — Marketplace App Integration

Publish applications to the platform (the platform) application marketplace. This skill
orchestrates two tool layers:

- **CLI** — `npx @mission_sciences/integration-wizard` for SDK installation,
  code generation, and verification (runs locally, already on npm)
- **MCP** — marketplace tools for authenticated marketplace operations (register,
  publish, upload assets, manage apps)

---

## When to Activate

Use this skill when the user wants to:

- Publish or list an app on the platform marketplace
- Integrate the Provider SDK into a web application
- Add JWT-based session management from the platform
- Register, update, or publish a marketplace application
- Upload icons or screenshots for a marketplace listing
- Verify an existing SDK integration
- Troubleshoot SDK or JWT issues

**Trigger phrases**: "the platform", "marketplace", "provider SDK",
"platform tokens", "application marketplace", "publish to marketplace",
"platform session", "integration wizard"

---

## CLI Tools

### Installation

The wizard is an npx package — no global install needed:

```bash
npx @mission_sciences/integration-wizard <command> [options]
```

### Global Options

| Flag | Description | Default |
|------|-------------|---------|
| `--dir <path>` | Project directory | `.` (current directory) |
| `--token <jwt>` | platform auth token (or `PLATFORM_TOKEN` env) | — |
| `--api-url <url>` | Wizard API URL | `https://wizard-api.dev.example.com` |
| `--framework <name>` | Skip framework prompt | — |

### Commands

#### `init` — Set Up SDK Integration

Scans the project, installs the Provider SDK, and generates framework-specific
integration code.

```bash
npx @mission_sciences/integration-wizard init --dir . --framework react
```

**Interactive flow** (when flags are omitted):

1. Select provider type: Application Provider or Data Provider
2. Scan project — detects framework, backend, TypeScript, package manager, SDK
3. Confirm or select framework (react | vue | vanilla)
4. Enter: applicationId, JWKS URI, backend language, identity provider, session timer
5. Install `@mission_sciences/provider-sdk` if not present
6. Generate files:
   - Frontend init + hooks/composition (framework-specific)
   - Backend JWT exchange endpoint (language-specific)
   - SDK configuration

**Non-interactive mode** (recommended for agents):

```bash
npx @mission_sciences/integration-wizard init \
  --dir . \
  --framework react
```

The wizard will still prompt for applicationId and JWKS URI if not found in
existing config. Supply these via prior configuration or answer prompts.

**Generated files by framework**:

| Framework | Frontend Files | Description |
|-----------|---------------|-------------|
| React | `usePlatformSession.ts`, `PlatformSessionProvider.tsx` | Hook + context provider |
| Vue | `usePlatformSession.ts`, `PlatformSessionPlugin.ts` | Composable + plugin |
| Vanilla | `session-client.js`, `session-ui.js` | Class + UI helpers |

**Backend exchange endpoints** (10 languages):

Express.js, Flask, Go (Gin), Spring Boot, ASP.NET Core, Rails, Laravel,
Actix-web (Rust), Ktor (Kotlin), Phoenix (Elixir)

Each generates a `/api/auth/token-exchange` endpoint that:
1. Receives the Platform JWT from the frontend
2. Validates the JWT signature against the JWKS endpoint
3. Extracts session claims (userId, orgId, applicationId)
4. Creates or finds the user in the app's database
5. Returns the app's own auth token

#### `verify` — Validate Integration

Runs 6 checks against the project:

```bash
npx @mission_sciences/integration-wizard verify --dir .
```

**Output**:
```
✓ Project detected (React + TypeScript)
✓ SDK installed (@mission_sciences/provider-sdk@1.x.x)
✓ Configuration valid (applicationId present)
✓ Framework integration found (usePlatformSession hook)
✓ JWKS endpoint reachable
✓ Test JWT validates successfully
```

- **Exit code 0** = all checks pass
- **Non-zero** = one or more failures (with error details)

If checks fail, use `chat` for AI-guided troubleshooting.

#### `chat` — AI Troubleshooting Assistant

Interactive AI chat with context about your project and integration state:

```bash
npx @mission_sciences/integration-wizard chat --dir .
```

- Streams responses from AWS Bedrock
- Aware of your framework, backend, config, and completed wizard steps
- Maintains conversation history within the session
- Use for debugging JWT validation, SDK configuration, or integration issues

#### `config` — Manage Wizard Settings

```bash
npx @mission_sciences/integration-wizard config show    # Show current config
npx @mission_sciences/integration-wizard config set <key> <value>
npx @mission_sciences/integration-wizard config reset   # Reset to defaults
```

Config stored at `~/.skill-wizard/config.json`.

---

## MCP Tools

Connect the Platform MCP server to access authenticated marketplace operations:

```bash
# Claude Code
claude mcp add provider --url https://mcp.platform.example.com/mcp

# With API key auth
claude mcp add provider --url https://mcp.platform.example.com/mcp \
  --header "Authorization: Bearer sk_..."
```

### Available Tools

#### `register_app`

Register a new application on the marketplace. Returns an `applicationId`.

**Required inputs**: `name`, `description`, `launchUrl`, `category`,
`baseCostPerSession` (USD), `sessionDurationMinutes`

**Optional inputs**: `tosRequired` (none | user | org | both), `tosContent`

**Example**:
```json
{
  "name": "Threat Intel Dashboard",
  "description": "Real-time threat intelligence visualization",
  "launchUrl": "https://my-app.example.com",
  "category": "threat-intelligence",
  "baseCostPerSession": 5.00,
  "sessionDurationMinutes": 60
}
```

Returns: `{ "applicationId": "app-uuid-here", ... }`

#### `publish_app`

Change an application's visibility status.

**Required inputs**: `applicationId`, `status`

**Status values**: `hidden` (default), `preview` (visible but not purchasable),
`available` (live on marketplace), `archived` (delisted)

#### `update_app`

Update an existing application's metadata.

**Required input**: `applicationId`

**Optional inputs**: `name`, `description`, `launchUrl`, `category`,
`baseCostPerSession`, `sessionDurationMinutes`

#### `get_app_status`

Check current registration and publish status.

**Required input**: `applicationId`

Returns full application details including status, metadata, and asset URLs.

#### `list_categories`

List all available marketplace categories. No inputs required.

Use before `register_app` to find the right category value.

#### `upload_asset`

Get a presigned S3 URL for uploading an app icon or screenshot.

**Required inputs**: `applicationId`, `assetType` (icon | screenshot),
`contentType` (image/png | image/jpeg)

Returns a presigned URL. Upload the file with a PUT request to the returned URL.

**Limits**: Icons 5MB max (PNG, JPEG, GIF, WebP). Screenshots 10MB max, 5 per app.

---

## Workflows

### New App — Build, Integrate, and Publish

Complete flow from building an app to listing it on the marketplace:

```
Step 1: Build the application (your normal development)

Step 2: Integrate the platform SDK (CLI)
  $ npx @mission_sciences/integration-wizard init --dir . --framework react
  → Installs @mission_sciences/provider-sdk
  → Generates usePlatformSession hook + backend exchange endpoint

Step 3: Verify the integration (CLI)
  $ npx @mission_sciences/integration-wizard verify --dir .
  → All 6 checks should pass

Step 4: List marketplace categories (MCP)
  → list_categories
  → Select the appropriate category

Step 5: Register on the marketplace (MCP)
  → register_app { name, description, launchUrl, category, ... }
  → Save the returned applicationId

Step 6: Upload assets (MCP)
  → upload_asset { applicationId, assetType: "icon", contentType: "image/png" }
  → Upload icon to the presigned URL
  → upload_asset { applicationId, assetType: "screenshot", ... }
  → Upload screenshots

Step 7: Publish (MCP)
  → publish_app { applicationId, status: "preview" }
  → App is now visible on the marketplace

Step 8: Report back to user
  → Provide the marketplace URL and applicationId
```

### Update Existing App

Update metadata or republish an existing application:

```
Step 1: Verify integration is still valid (CLI)
  $ npx @mission_sciences/integration-wizard verify --dir .

Step 2: Update app metadata (MCP)
  → update_app { applicationId, ...fieldsToUpdate }

Step 3: Upload new assets if needed (MCP)
  → upload_asset { ... }

Step 4: Publish if status changed (MCP)
  → publish_app { applicationId, status: "available" }
```

### Debug Integration Issues

Diagnose and fix SDK or JWT problems:

```
Step 1: Run verification (CLI)
  $ npx @mission_sciences/integration-wizard verify --dir .
  → Note which checks fail

Step 2: If JWKS or JWT checks fail:
  → Verify the JWKS URI is correct in config
  → Check network access to platform.example.com
  → Ensure applicationId matches a registered app

Step 3: If framework check fails:
  → Verify the generated hook/composable file exists
  → Check imports in the main app entry point

Step 4: Use AI assistant for complex issues (CLI)
  $ npx @mission_sciences/integration-wizard chat --dir .
  → Describe the issue — the AI has full context of your project
```

---

## Framework Notes

### React

`init` generates:
- `usePlatformSession.ts` — React hook wrapping `MarketplaceSDK`
- `PlatformSessionProvider.tsx` — Context provider for session state
- Backend exchange endpoint (in your chosen language)

The hook provides: `{ session, loading, timeRemaining, sdk }`.
Wrap your app in `<PlatformSessionProvider>` and call `usePlatformSession()` in components.

### Vue

`init` generates:
- `usePlatformSession.ts` — Vue 3 composable using `ref()` and `onMounted()`
- `PlatformSessionPlugin.ts` — Vue plugin for app-wide session access
- Backend exchange endpoint

Use `const { session, loading, timeRemaining } = usePlatformSession()` in setup.

### Vanilla JavaScript

`init` generates:
- `session-client.js` — Class wrapping `MarketplaceSDK`
- `session-ui.js` — Optional DOM helpers for session timer display
- Backend exchange endpoint

Instantiate the class and call `initialize()`. Use event callbacks for UI updates.

### Backend Languages

All backends generate a JWT exchange endpoint at `/api/auth/token-exchange` with
the same logic: validate Platform JWT → extract claims → find/create user → return
app token. The implementation uses each language's standard JWT and HTTP
libraries.

| Language | JWT Library | HTTP Framework |
|----------|------------|----------------|
| Node.js (Express) | `jsonwebtoken` + `jwks-rsa` | Express |
| Python (Flask) | `PyJWT` + `cryptography` | Flask |
| Go | `golang-jwt/jwt` | Gin |
| Java | `nimbus-jose-jwt` | Spring Boot |
| C# | `Microsoft.IdentityModel` | ASP.NET Core |
| Ruby | `jwt` gem | Rails |
| PHP | `firebase/php-jwt` | Laravel |
| Rust | `jsonwebtoken` crate | Actix-web |
| Kotlin | `nimbus-jose-jwt` | Ktor |
| Elixir | `joken` | Phoenix |

---

## SDK Configuration Reference

The `@mission_sciences/provider-sdk` accepts this configuration:

```typescript
{
  // Required
  applicationId: string,     // From register_app or platform admin
  jwksUri: string,           // Default: https://api.platform.example.com/.well-known/jwks.json

  // Session behavior
  jwtParamName: string,      // URL param name for JWT (default: "gwSession")
  autoStart: boolean,        // Auto-start session on init (default: true)
  warningThresholdSeconds: number, // Warning before expiry (default: 300)
  marketplaceUrl: string,    // marketplace URL

  // Lifecycle hooks
  onSessionStart: (ctx) => void,   // Fires after JWT validation
  onSessionEnd: (ctx) => void,     // Fires on expiration or manual end
  onSessionWarning: (ctx) => void, // Fires near expiration
  onSessionExtend: (ctx) => void,  // Fires after extension

  // Advanced (Phase 2)
  useBackendValidation: boolean,   // Validate JWT on backend only
  enableHeartbeat: boolean,        // Heartbeat pings
  enableTabSync: boolean,          // Cross-tab session sync
  pauseOnHidden: boolean           // Pause timer when tab hidden
}
```

**Session context** (passed to all hooks):
```typescript
{
  sessionId: string,
  userId: string,
  email?: string,
  orgId: string,
  applicationId: string,
  durationMinutes: number,
  expiresAt: number,        // Unix timestamp
  jwt: string               // Raw JWT for backend exchange
}
```

---

## References

For detailed specifications, see the `references/` directory:

- **[SDK Quick Reference](references/sdk-quick-reference.md)** — Full SDK API surface, methods, events
- **[JWT Specification](references/jwt-specification.md)** — JWT claims, JWKS endpoint, validation flow
- **[API Endpoints](references/api-endpoints.md)** — Platform API application and session endpoints
- **[Framework Patterns](references/framework-patterns.md)** — Detailed patterns for each framework + backend
- **[Troubleshooting](references/troubleshooting.md)** — Common issues and resolution steps

---

## Important Notes

- The integration wizard detects your project's framework and package manager
  automatically. You rarely need to specify `--framework` manually.
- The SDK package is `@mission_sciences/provider-sdk` (not `sdk`).
- JWT parameter name defaults to `gwSession` in the URL query string.
- The JWKS endpoint for JWT validation is public and requires no authentication.
- MCP tools require authentication (OAuth or API key). CLI tools work without
  platform auth for code generation; only `verify` and `chat` need network access.
- Applications start in `hidden` status. Set to `preview` or `available` to
  make them visible on the marketplace.
