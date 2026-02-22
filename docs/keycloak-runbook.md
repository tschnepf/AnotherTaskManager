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
7. Validate OIDC public endpoint reachability using `docs/oidc-public-endpoints-runbook.md`.

## Fresh deployment bootstrap (single first-admin command)
1. Enable web/mobile IdP auth and JIT provisioning in environment:
   - `KEYCLOAK_AUTH_ENABLED=true`
   - `MOBILE_API_ENABLED=true`
   - `KEYCLOAK_WEB_AUTH_ENABLED=true`
   - `KEYCLOAK_WEB_CLIENT_ID=taskhub-web`
   - `KEYCLOAK_AUTO_PROVISION_USERS=true`
   - `KEYCLOAK_AUTO_PROVISION_ORGANIZATION=true`
2. Create first admin in both Keycloak and Django with one command:
```bash
docker exec -it taskhub-api python backend/manage.py bootstrap_idp_admin \
  --email admin@example.com \
  --password 'REPLACE_WITH_STRONG_PASSWORD' \
  --first-name Admin \
  --last-name User \
  --organization-name "Task Hub" \
  --role owner
```
3. Use `/login` web page -> `Continue with TaskHub ID` (OIDC).
4. iOS login uses same IdP credentials.

## Fresh deployment bootstrap (web-only, no CLI user creation)
1. Enable in environment:
   - `KEYCLOAK_AUTH_ENABLED=true`
   - `MOBILE_API_ENABLED=true`
   - `KEYCLOAK_WEB_AUTH_ENABLED=true`
   - `KEYCLOAK_WEB_CLIENT_ID=taskhub-web`
   - `KEYCLOAK_WEB_SIGNUP_ENABLED=true`
   - `KEYCLOAK_AUTO_PROVISION_USERS=true`
   - `KEYCLOAK_AUTO_PROVISION_ORGANIZATION=true`
2. Ensure realm registration is enabled (in realm export this is now default):
   - `registrationAllowed=true`
   - `registrationEmailAsUsername=true`
3. Open app `/login` and click `Create account`.
4. Complete Keycloak signup page.
5. On first successful OIDC callback:
   - Keycloak user exists
   - Django user is auto-created and linked
   - first auto-provisioned user is app superuser/staff + owner
6. Use same credentials for iOS and web.

## Migration + onboarding
1. Export existing Django users to CSV:
```bash
bash tools/keycloak/export-django-users.sh /tmp/taskhub-users.csv
```
2. Run migration dry-run report (creates users in Keycloak when `--apply` is added):
```bash
bash tools/keycloak/migrate-users.sh /tmp/taskhub-users.csv --report /tmp/keycloak-migrate-report.json
```
3. Apply migration (recommended: temporary bootstrap password):
```bash
bash tools/keycloak/migrate-users.sh /tmp/taskhub-users.csv \
  --apply \
  --set-password \
  --default-password 'REPLACE_WITH_TEMP_PASSWORD' \
  --temporary-password \
  --report /tmp/keycloak-migrate-apply-report.json
```
4. Link Keycloak subjects to existing Django users by matching email (dry-run first):
```bash
bash tools/keycloak/link-identities-by-email.sh \
  --issuer https://tasks.example.com/idp/realms/taskhub \
  --report /tmp/oidc-link-dry-run.json
```
5. Apply identity linking:
```bash
bash tools/keycloak/link-identities-by-email.sh \
  --issuer https://tasks.example.com/idp/realms/taskhub \
  --apply \
  --report /tmp/oidc-link-apply-report.json
```
6. Optional advanced linking from curated mappings:
```bash
python tools/keycloak/backfill_oidc_identity.py \
  --csv /path/to/identity-links.csv \
  --issuer https://tasks.example.com/idp/realms/taskhub \
  --apply \
  --report /tmp/oidc-backfill-report.json
```
7. Validate a migrated user can sign into Keycloak (mobile flow), then access:
   - `GET /api/mobile/v1/session` (200)
   - `GET /api/mobile/v1/tasks` (200 with bearer token)

## Key rotation
1. Add a new active signing key in Keycloak; keep the previous key available during overlap.
2. Confirm mobile API accepts tokens from both keys during overlap window.
3. Remove old key only after `KEYCLOAK_JWKS_HARD_TTL_SECONDS` window has elapsed.

## Incident handling
1. If token validation failures spike, verify reverse-proxy host headers and issuer URL first.
2. Temporarily disable mobile traffic by setting `MOBILE_API_ENABLED=false` if auth incident is unresolved.
3. Preserve legacy web auth while mobile auth is degraded.

## JIT provisioning (recommended for fresh installs)
1. Enable automatic first-login provisioning:
   - `KEYCLOAK_AUTO_PROVISION_USERS=true`
   - `KEYCLOAK_AUTO_PROVISION_ORGANIZATION=true`
2. With both enabled, successful OIDC login automatically:
   - creates/links local Django user by token email claim
   - creates an organization for brand-new users
   - creates `OIDCIdentity` issuer/subject mapping
3. Keep `KEYCLOAK_AUTO_PROVISION_USERS=false` if you require explicit admin onboarding only.

## Rollback
1. Set `KEYCLOAK_AUTH_ENABLED=false` and `MOBILE_API_ENABLED=false`.
2. Keep `/auth/*` cookie-based web auth active.
3. Re-enable mobile flags only after Keycloak health, issuer config, and identity mappings are revalidated.
