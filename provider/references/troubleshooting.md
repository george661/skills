# Troubleshooting Provider Integration

## Diagnostic Steps

Always start with the verification command:

```bash
npx @mission_sciences/integration-wizard verify --dir .
```

This runs 6 checks. The output tells you exactly what failed and why.

---

## Common Issues

### 1. "SDK not installed"

**Symptom**: Verify reports SDK not found.

**Fix**:
```bash
npm install @mission_sciences/provider-sdk
# or
yarn add @mission_sciences/provider-sdk
# or
pnpm add @mission_sciences/provider-sdk
```

Verify the package appears in `package.json` under `dependencies`.

### 2. "Configuration invalid — applicationId missing"

**Symptom**: Verify reports missing applicationId.

**Fix**: Ensure your SDK initialization includes `applicationId`:

```typescript
new MarketplaceSDK({
  applicationId: 'your-app-id-from-registration',
  // ...
});
```

If you haven't registered yet, use the MCP tool `register_app` first.

### 3. "Framework integration not found"

**Symptom**: Verify cannot find the generated hook/composable.

**Causes**:
- Files were generated but moved or renamed
- Files were generated for a different framework than detected

**Fix**:
- Check that the generated files exist (e.g., `usePlatformSession.ts` for React)
- Re-run `init` if files are missing:
  ```bash
  npx @mission_sciences/integration-wizard init --dir . --framework react
  ```

### 4. "JWKS endpoint unreachable"

**Symptom**: Verify cannot reach the JWKS endpoint.

**Causes**:
- Network/firewall blocking `api.platform.example.com`
- Wrong JWKS URI in configuration
- Development environment without internet access

**Fix**:
- Test connectivity: `curl https://api.platform.example.com/.well-known/jwks.json`
- Check the `jwksUri` in your SDK config matches the correct environment
- Default: `https://api.platform.example.com/.well-known/jwks.json`

### 5. "Test JWT validation failed"

**Symptom**: JWT signature validation fails during verify.

**Causes**:
- JWKS keys don't match the JWT's `kid`
- Clock skew between your machine and the server
- Expired test JWT

**Fix**:
- Ensure you're using the correct JWKS URI for your environment
- Check system clock: `date -u` should match UTC
- Generate a fresh test JWT via the wizard API

### 6. "Session not starting in browser"

**Symptom**: `onSessionStart` never fires.

**Causes**:
- JWT not present in URL query parameter
- `jwtParamName` mismatch (default is `gwSession`)
- SDK `initialize()` not called or called before DOM ready

**Fix**:
- Check URL contains `?gwSession=eyJ...`
- Verify `jwtParamName` in config matches the URL parameter
- Ensure `initialize()` is awaited:
  ```typescript
  await sdk.initialize();
  ```

### 7. "Backend exchange endpoint returns 401"

**Symptom**: `/api/auth/token-exchange` rejects the JWT.

**Causes**:
- Backend JWKS fetch failing
- JWT expired between frontend init and backend exchange
- applicationId mismatch in backend validation

**Fix**:
- Verify backend can reach `api.platform.example.com` (not blocked by CORS/proxy)
- Log the JWT claims and check `exp` vs current time
- Ensure backend validates against the same applicationId

### 8. "Package manager not detected"

**Symptom**: Wrong package manager used during `init`.

**Detection order**:
1. `pnpm-lock.yaml` → pnpm
2. `yarn.lock` → yarn
3. Fallback → npm

**Fix**: Ensure the correct lock file exists, or specify manually.

### 9. "Backend language not detected"

**Symptom**: Wizard asks for backend language when it should detect.

**Detection method**: Scans `package.json` dependencies (for Node frameworks),
or checks for language-specific files (`go.mod`, `requirements.txt`, `pom.xml`,
`*.csproj`).

**Fix**: Ensure your project has the standard files for your language/framework.

### 10. "Presigned upload URL expired"

**Symptom**: PUT to presigned URL returns 403.

**Cause**: Presigned URLs expire after 5 minutes.

**Fix**: Request a new presigned URL via `upload_asset` and upload immediately.

---

## AI Chat Troubleshooting

For complex issues, use the built-in AI assistant:

```bash
npx @mission_sciences/integration-wizard chat --dir .
```

The AI has context about:
- Your detected framework and backend
- Your current wizard step and config
- Common mistakes for your specific stack
- SDK documentation and patterns

Describe your issue in plain language. The AI can suggest specific code changes.

---

## Environment-Specific Notes

### Replit

- `launchUrl` should use the Repl's public URL (e.g., `https://my-app.repl.co`)
- Ensure Node.js 18+ in your Repl (check with `node --version`)
- The wizard's `--dir .` works from the Repl root

### Local Development

- Use `--api-url` flag if targeting a non-default wizard API
- Set `PLATFORM_TOKEN` env var for authenticated operations
- The SDK will look for `gwSession` in `window.location.search`

### Docker / Containerized

- JWKS endpoint must be reachable from the container
- Backend exchange endpoint must be accessible from the frontend
- Mount config at `~/.skill-wizard/config.json` or re-run `init`

---

## Getting Help

1. Run `verify` to get specific failure messages
2. Try `chat` for AI-guided resolution
3. Check the SDK README: `@mission_sciences/provider-sdk`
4. Check the Integration Guide in the SDK package
