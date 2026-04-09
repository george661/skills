# Framework Integration Patterns

Detailed patterns for each frontend framework and backend language supported
by the Integration Wizard.

## Frontend Frameworks

### React

**Generated files**:
- `src/hooks/usePlatformSession.ts` — Session hook
- `src/providers/PlatformSessionProvider.tsx` — Context provider

**Hook pattern**:
```typescript
import { useState, useEffect, useRef } from 'react';
import { MarketplaceSDK } from '@mission_sciences/provider-sdk';

export function usePlatformSession() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [timeRemaining, setTimeRemaining] = useState(0);
  const sdkRef = useRef(null);

  useEffect(() => {
    const sdk = new MarketplaceSDK({
      applicationId: 'YOUR_APP_ID',
      jwksUri: 'https://api.platform.example.com/.well-known/jwks.json',
      onSessionStart: (ctx) => {
        setSession(ctx);
        setLoading(false);
        // Exchange Platform JWT for your app token:
        fetch('/api/auth/token-exchange', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jwt: ctx.jwt })
        });
      },
      onSessionEnd: () => setSession(null),
      onSessionWarning: (ctx) => { /* show warning UI */ },
    });
    sdkRef.current = sdk;
    sdk.initialize().catch(() => setLoading(false));

    const timer = setInterval(() => {
      setTimeRemaining(sdk.getRemainingTime());
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  return { session, loading, timeRemaining, sdk: sdkRef.current };
}
```

**Usage in component**:
```tsx
function App() {
  const { session, loading, timeRemaining, sdk } = usePlatformSession();
  if (loading) return <LoadingSpinner />;
  if (!session) return <NoSessionMessage />;
  return <YourApp session={session} />;
}
```

### Vue 3

**Generated files**:
- `src/composables/usePlatformSession.ts` — Composition API composable
- `src/plugins/gwSession.ts` — Vue plugin (optional)

**Composable pattern**:
```typescript
import { ref, onMounted, onUnmounted } from 'vue';
import { MarketplaceSDK } from '@mission_sciences/provider-sdk';

export function usePlatformSession() {
  const session = ref(null);
  const loading = ref(true);
  const timeRemaining = ref(0);
  let sdk = null;
  let timer = null;

  onMounted(async () => {
    sdk = new MarketplaceSDK({
      applicationId: 'YOUR_APP_ID',
      jwksUri: 'https://api.platform.example.com/.well-known/jwks.json',
      onSessionStart: (ctx) => {
        session.value = ctx;
        loading.value = false;
      },
      onSessionEnd: () => { session.value = null; },
    });
    await sdk.initialize().catch(() => { loading.value = false; });

    timer = setInterval(() => {
      timeRemaining.value = sdk.getRemainingTime();
    }, 1000);
  });

  onUnmounted(() => { if (timer) clearInterval(timer); });

  return { session, loading, timeRemaining };
}
```

### Vanilla JavaScript

**Generated files**:
- `src/session-client.js` — Session manager class
- `src/session-ui.js` — DOM helper for timer display

**Class pattern**:
```javascript
import { MarketplaceSDK } from '@mission_sciences/provider-sdk';

class PlatformSession {
  constructor(config) {
    this.sdk = new MarketplaceSDK({
      applicationId: config.applicationId,
      jwksUri: config.jwksUri,
      onSessionStart: (ctx) => this._onStart(ctx),
      onSessionEnd: (ctx) => this._onEnd(ctx),
      onSessionWarning: (ctx) => this._onWarning(ctx),
    });
    this.session = null;
    this.callbacks = {};
  }

  async initialize() {
    await this.sdk.initialize();
  }

  on(event, callback) { this.callbacks[event] = callback; }
  _onStart(ctx) { this.session = ctx; this.callbacks.start?.(ctx); }
  _onEnd(ctx) { this.session = null; this.callbacks.end?.(ctx); }
  _onWarning(ctx) { this.callbacks.warning?.(ctx); }
}
```

---

## Backend Exchange Endpoints

All backends implement the same logic with language-appropriate libraries.

### Node.js (Express)

```typescript
import express from 'express';
import jwt from 'jsonwebtoken';
import jwksClient from 'jwks-rsa';

const client = jwksClient({ jwksUri: JWKS_URI, cache: true });

function getKey(header, callback) {
  client.getSigningKey(header.kid, (err, key) => {
    callback(err, key?.getPublicKey());
  });
}

app.post('/api/auth/token-exchange', async (req, res) => {
  const { jwt: gwToken } = req.body;
  jwt.verify(gwToken, getKey, { issuer: 'platform.example.com' }, (err, decoded) => {
    if (err) return res.status(401).json({ error: 'Invalid token' });
    if (decoded.applicationId !== APP_ID) return res.status(403).json({ error: 'Wrong app' });
    // Find or create user, generate app token...
    res.json({ token: appToken, user: { id: decoded.userId } });
  });
});
```

### Python (Flask)

```python
import jwt
from jwt import PyJWKClient

jwks_client = PyJWKClient(JWKS_URI)

@app.route('/api/auth/token-exchange', methods=['POST'])
def token_exchange():
    platform_token = request.json.get('jwt')
    signing_key = jwks_client.get_signing_key_from_jwt(platform_token)
    decoded = jwt.decode(platform_token, signing_key.key, algorithms=['RS256'],
                         issuer='platform.example.com')
    assert decoded['applicationId'] == APP_ID
    # Find or create user, generate app token...
    return jsonify({'token': app_token, 'user': {'id': decoded['userId']}})
```

### Go (Gin)

```go
func gwExchange(c *gin.Context) {
    var body struct{ JWT string `json:"jwt"` }
    c.BindJSON(&body)

    set, _ := jwk.Fetch(context.Background(), jwksURI)
    token, _ := jwt.Parse([]byte(body.JWT), jwt.WithKeySet(set),
        jwt.WithIssuer("platform.example.com"))

    appID, _ := token.Get("applicationId")
    if appID != expectedAppID { c.AbortWithStatus(403); return }

    // Find or create user, generate app token...
    c.JSON(200, gin.H{"token": appToken})
}
```

### Spring Boot (Java)

```java
@PostMapping("/api/auth/token-exchange")
public ResponseEntity<?> gwExchange(@RequestBody Map<String, String> body) {
    String gwToken = body.get("jwt");
    JWKSource<SecurityContext> source = new RemoteJWKSet<>(new URL(jwksUri));
    JWSVerifier verifier = // build from JWK matching kid
    SignedJWT sjwt = SignedJWT.parse(gwToken);
    if (!sjwt.verify(verifier)) throw new AuthException("Invalid");
    JWTClaimsSet claims = sjwt.getJWTClaimsSet();
    // Validate issuer, applicationId, expiry...
    // Find or create user, generate app token...
    return ResponseEntity.ok(Map.of("token", appToken));
}
```

### ASP.NET Core (C#)

```csharp
[HttpPost("api/auth/token-exchange")]
public async Task<IActionResult> GwExchange([FromBody] GwExchangeRequest req) {
    var handler = new JwtSecurityTokenHandler();
    var keys = await new HttpClient().GetStringAsync(jwksUri);
    var jwks = new JsonWebKeySet(keys);
    var parameters = new TokenValidationParameters {
        ValidIssuer = "platform.example.com",
        IssuerSigningKeys = jwks.Keys,
    };
    var principal = handler.ValidateToken(req.Jwt, parameters, out _);
    var appId = principal.FindFirst("applicationId")?.Value;
    // Validate, find/create user, generate app token...
    return Ok(new { token = appToken });
}
```

---

## Project Scanner Detection

The integration wizard's scanner detects your stack automatically:

| Detection | Method |
|-----------|--------|
| React | `react` in package.json dependencies |
| Vue | `vue` in package.json dependencies |
| Vanilla | No React or Vue detected |
| TypeScript | `tsconfig.json` exists |
| npm | Default, or `package-lock.json` |
| yarn | `yarn.lock` present |
| pnpm | `pnpm-lock.yaml` present |
| SDK installed | `@mission_sciences/provider-sdk` in dependencies |
| Backend lang | Dependency detection (e.g., `express` → Node, `flask` → Python) or file detection (e.g., `go.mod` → Go) |

## Template Registry

Templates are registered by framework + step + backend language. The wizard
selects the correct template based on scanner results and user choices.

**Frontend templates**: One set per framework (React, Vue, Vanilla)
**Backend templates**: One per language (10 languages)
**Shared templates**: Package installation script (npm/yarn/pnpm)
