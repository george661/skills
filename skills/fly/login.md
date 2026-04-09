---
name: fly:login
description: Login to a Concourse target using AWS Secrets Manager credentials (headless) or browser auth fallback.
---

# login

Login to a Concourse CI target. Resolves credentials automatically from multiple sources, preferring headless authentication via AWS Secrets Manager.

## Credential Resolution Order

1. **AWS Secrets Manager** — `concourse/local-user` secret in `us-east-1` (format: `username:password`)
2. **Environment variables** — `FLY_TARGET`, `CONCOURSE_URL`, `CONCOURSE_USERNAME`, `CONCOURSE_PASSWORD`
3. **Project credentials** — `$PROJECT_ROOT/.claude/credentials.json`
4. **Project .env** — `$PROJECT_ROOT/.env`
5. **User settings** — `~/.claude/settings.json` under `credentials.fly`

When username/password are available (from any source), uses `fly login -u/-p` for headless auth. Otherwise falls back to `fly login -b` (browser).

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | string | No | Concourse target name (default: `main`) |
| `url` | string | No | Concourse server URL (default: `https://ci.dev.example.com`) |
| `username` | string | No | Override username |
| `password` | string | No | Override password |

## Example

```bash
# Login using auto-resolved credentials (AWS secret → env → .env → settings)
npx tsx ~/.claude/skills/fly/login.ts '{}'

# Login with explicit credentials
npx tsx ~/.claude/skills/fly/login.ts '{"target": "main", "url": "https://ci.dev.example.com"}'
```

## Response

```json
{
  "success": true,
  "target": "main",
  "url": "https://ci.dev.example.com",
  "authMethod": "username/password",
  "message": "Logged in to target \"main\" at https://ci.dev.example.com via username/password authentication"
}
```

## Notes

- The AWS secret `concourse/local-user` is fetched using the default AWS profile (dev account)
- Credentials are cached by fly in `~/.flyrc` after login — subsequent fly commands don't re-authenticate until the token expires
- The `fly-client.ts` auto-login logic also uses this credential chain, so all fly skills benefit automatically
- If AWS credentials aren't available (e.g., no SSO session), falls through to the next source silently
