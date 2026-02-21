# OIDC Public Endpoints Runbook

## Purpose
Mobile OIDC bootstrap requires these endpoints to be public (no auth, no challenge):
1. `GET /idp/realms/<realm>/.well-known/openid-configuration`
2. `GET /idp/realms/<realm>/protocol/openid-connect/certs`

These endpoints are safe to expose publicly and do not contain secrets.

## Required behavior
1. HTTP `200`
2. `Content-Type: application/json`
3. Body is valid JSON
4. No login redirect, no HTML challenge page

## Reverse proxy requirements
1. Ensure `/idp/*` routes to Keycloak.
2. Keep `/api/mobile/*` auth behavior unchanged (still bearer token protected).
3. Optional: add short cache headers for discovery/JWKS (for example `max-age=300`).

## Cloudflare/WAF rules (tasks.tardis-proxy.com)
Create a rule that bypasses challenge/WAF for the two exact OIDC config endpoints:

```text
http.host eq "tasks.tardis-proxy.com" and (
  http.request.uri.path eq "/idp/realms/taskhub/.well-known/openid-configuration" or
  http.request.uri.path eq "/idp/realms/taskhub/protocol/openid-connect/certs"
)
```

Recommended action:
1. Skip `Managed Challenge`
2. Skip `JS Challenge`
3. Skip WAF managed rules for these paths
4. Keep normal protections for all other paths

Do not bypass protections for `/api/mobile/*` business endpoints.

## Validation commands
Discovery JSON:
```bash
curl -sS -H "Accept: application/json" \
  https://tasks.tardis-proxy.com/idp/realms/taskhub/.well-known/openid-configuration \
  | jq . | head -n 50
```

Discovery headers:
```bash
curl -sS -I \
  https://tasks.tardis-proxy.com/idp/realms/taskhub/.well-known/openid-configuration
```

JWKS JSON:
```bash
JWKS_URL=$(curl -sS -H "Accept: application/json" \
  https://tasks.tardis-proxy.com/idp/realms/taskhub/.well-known/openid-configuration \
  | jq -r .jwks_uri)

curl -sS -H "Accept: application/json" "$JWKS_URL" | jq .
```

Protected API remains protected:
```bash
curl -i https://tasks.tardis-proxy.com/api/mobile/v1/tasks
```

Expected: `401` or `403` without token.
