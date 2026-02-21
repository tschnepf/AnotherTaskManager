# Keycloak Runbook

## Local bootstrap
1. Start compose services.
2. Open Keycloak admin console at `/idp/admin`.
3. Import `tools/keycloak/realm-export/taskhub-realm.json`.
4. Confirm iOS public client `taskhub-mobile` and redirect URI `taskhubmobile://oauth/callback`.
5. Confirm the `taskhub-mobile` client includes a `sub` protocol mapper (`oidc-sub-mapper`) for access tokens.
6. Validate export hygiene:
```bash
bash tools/keycloak/validate-realm-export.sh tools/keycloak/realm-export/taskhub-realm.json
```

## Migration + onboarding
1. Prepare CSV of users for IdP migration with columns `email,first_name,last_name,enabled`.
2. Run migration dry-run report:
```bash
bash tools/keycloak/migrate-users.sh /path/to/users.csv --report /tmp/keycloak-migrate-report.json
```
3. After successful migration, backfill identity links (dry-run first):
```bash
python tools/keycloak/backfill_oidc_identity.py \
  --csv /path/to/identity-links.csv \
  --issuer https://tasks.example.com/idp/realms/taskhub
```
4. Apply identity backfill:
```bash
python tools/keycloak/backfill_oidc_identity.py \
  --csv /path/to/identity-links.csv \
  --issuer https://tasks.example.com/idp/realms/taskhub \
  --apply \
  --report /tmp/oidc-backfill-report.json
```

## Key rotation
1. Add a new active signing key in Keycloak; keep the previous key available during overlap.
2. Confirm mobile API accepts tokens from both keys during overlap window.
3. Remove old key only after `KEYCLOAK_JWKS_HARD_TTL_SECONDS` window has elapsed.

## Incident handling
1. If token validation failures spike, verify reverse-proxy host headers and issuer URL first.
2. Temporarily disable mobile traffic by setting `MOBILE_API_ENABLED=false` if auth incident is unresolved.
3. Preserve legacy web auth while mobile auth is degraded.

## Rollback
1. Set `KEYCLOAK_AUTH_ENABLED=false` and `MOBILE_API_ENABLED=false`.
2. Keep `/auth/*` cookie-based web auth active.
3. Re-enable mobile flags only after Keycloak health, issuer config, and identity mappings are revalidated.
