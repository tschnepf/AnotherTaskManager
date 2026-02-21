# Task Hub iOS Server + Backend Implementation Plan (Self-Hosted Keycloak)

This document is the server/backend/infra execution track split from `Spec/ios-mobile-implementation-plan.md`.
The Xcode/iOS app execution track lives in `Spec/ios-xcode-app-implementation-plan.md`.

## Goal
Deliver the most reliable self-hosted iOS experience for Task Hub with:
1. Dedicated self-hosted IdP (Keycloak) for OAuth/OIDC + PKCE.
2. Mobile API split and versioned contract.
3. Reliable APNs notifications with retry/cancel/audit.
4. Siri task creation with idempotency safety.
5. Widget data via compact snapshot + offline cache.

## 0. Locked Decisions
1. Identity provider is self-hosted Keycloak.
2. iOS user enters one Task Hub base URL (same domain the browser uses).
3. Browser and iOS traffic both pass through the same reverse proxy domain.
4. Keycloak is exposed on the same domain under `/idp`.
5. Native auth is OIDC Authorization Code + PKCE via `ASWebAuthenticationSession`.
6. Existing web auth (`/auth/*` cookie + CSRF) remains functional during rollout.

## 1. Non-Negotiable Backend Contracts

### 1.1 Identity provisioning policy
1. Never auto-create a new organization from mobile auth.
2. Resolve Keycloak identity by (`issuer`, `sub`) against `OIDCIdentity`.
3. If no mapping exists, return `403 onboarding_required`.
4. User/org linking happens only via explicit admin onboarding flow, migration script, or approved admin API.

### 1.2 Onboarding policy
1. Provide a deterministic onboarding mechanism for post-migration users.
2. Support both:
   - admin-only API to create/link identity mapping
   - admin CLI/script for bulk link operations
3. Every link/unlink action is audit logged.

### 1.3 Tenancy and privacy policy
1. Mobile APIs preserve current tenancy behavior.
2. Cross-organization resource access returns `404` (not `403`).
3. All list/detail queries are org-scoped from authenticated identity, never from client-provided org IDs.
4. IdP token claims prove identity only; org membership and role authorization are always resolved from local DB mappings.

### 1.4 Token and scope policy
1. Required OIDC scopes include `openid`.
2. For refresh-capable native sessions, request `offline_access`.
3. API authorization scopes:
   - `mobile.read`
   - `mobile.write`
   - `mobile.sync`
   - `mobile.notify`
4. API validates token `iss`, `aud`, `exp`, `nbf` (if present), and required scope.
5. API enforces token signature algorithm allowlist.
6. API enforces max clock skew tolerance.
7. API rejects unsupported token types/uses.

### 1.5 JWKS verification policy
1. Validate JWT locally using JWKS cache.
2. On unknown `kid`, refresh JWKS once and retry verification.
3. Use soft TTL and hard TTL for JWKS cache.
4. Use fetch timeout and bounded retries.
5. If JWKS refresh fails and hard TTL is exceeded, reject request.

### 1.6 Idempotency policy
1. Mobile create endpoints require `Idempotency-Key`.
2. Reused key + same canonical payload hash returns original response.
3. Reused key + different payload hash returns `409 idempotency_conflict`.

### 1.7 Sync and retention policy
1. Delta sync is append-only cursor-based.
2. Cursor is an opaque string token from the server; clients must not parse or infer numeric meaning.
3. Cursor contract:
   - `200` with events + `next_cursor`
   - `410 cursor_expired` with full-resync instruction
4. Task deletions emit tombstones.
5. Event emission uses `transaction.on_commit`.
6. Event retention purge is scheduled and tested.

### 1.8 Error response envelope policy
1. All non-2xx `/api/mobile/v1/*` responses return a stable JSON envelope:
   - `{"error":{"code":"<machine_code>","message":"<human_message>","details":{}},"request_id":"<id>"}`
2. Clients must branch on `error.code`, not `error.message`.
3. Required machine codes:
   - `onboarding_required` (`403`)
   - `cursor_expired` (`410`)
   - `idempotency_conflict` (`409`)
   - `insufficient_scope` (`403`)
   - `invalid_audience` (`401`)
   - `invalid_token` (`401`)

### 1.9 APNs device contract policy
1. Device registration payload includes:
   - APNs token
   - `apns_environment` (`sandbox` or `production`)
   - stable `device_installation_id`
   - app version/build
   - iOS version/timezone
2. App bundle identifier must match server/APNs credential bundle configuration (`APNS_BUNDLE_ID`).
3. Device `apns_environment` must align with the server's APNs runtime environment selection.

## 2. Reliability Principles
1. Keycloak is a dedicated service, not embedded in Django.
2. API avoids per-request token introspection calls.
3. Notification pipeline supports dedupe, retry, cancel, dead-token cleanup, and worker-safe claiming.
4. Writes requiring exactly-once behavior are idempotency-protected.
5. Production reliability target includes Keycloak HA artifacts and failover validation.

## 3. Execution Contract
1. Execute steps in order.
2. Do not skip validation gates.
3. Do not break current web behavior.
4. Run legacy regression tests after every backend step.

Regression gate after each backend step:
```bash
. .venv/bin/activate
pytest -q backend/tests/test_auth_tenant.py backend/tests/test_tasks_api.py backend/tests/test_projects_tags_views_api.py
```

## 3.1 Execution Ownership (Where Work Happens)
Use this split to avoid doing the wrong work in the wrong environment.

### Track A - Server/Backend/Infra (execute from this repo + deployment environment)
1. Perform all architecture, infrastructure, backend model, API, auth, sync, APNs, and rollout work in:
   - Sections `5` through `9`
   - Section `11`
   - Section `13`
   - Section `14`
2. Execute all `Step S0` through `Step S17` from this repository and server tooling (Docker, Django, Celery, nginx, Keycloak scripts).
3. Run backend validation commands and regression gates locally/CI from this repo.

### Track B - Cross-track validation
1. Section `12` is integration validation and must be run after both tracks have working implementations.
2. End-to-end behavior is only complete when server and iOS validations both pass.

## 4. Prerequisites
1. Apple Developer account and APNs key data.
2. DNS + TLS for Task Hub domain.
3. Reverse proxy control.
4. Docker deployment access.
5. Keycloak bootstrap admin credentials.

## 5. Target Architecture

### 5.1 URL and routing model
1. User enters `https://tasks.example.com` in iOS app.
2. App validates:
   - `GET /health/live`
   - `GET /api/mobile/v1/meta`
3. Reverse proxy routes:
   - `/api/mobile/v1/*` -> Django API
   - `/idp/*` -> Keycloak
   - existing web routes unchanged
4. `GET /api/mobile/v1/meta` returns OIDC discovery URL for same host, for example:
   - `https://tasks.example.com/idp/realms/taskhub/.well-known/openid-configuration`

### 5.2 Canonical host policy
1. Backend accepts discovery host from request host only if in allowlist.
2. Optional strict override with `KEYCLOAK_PUBLIC_BASE_URL`.
3. If host is not allowed, `/api/mobile/v1/meta` returns validation error.

### 5.3 Auth model
1. Keycloak realm: `taskhub`.
2. iOS client is public client with PKCE and redirect URI allowlist.
3. Access token audience is API-specific and validated in Django.

### 5.4 Audience/resource model
1. Define dedicated audience for Task Hub API (for example `taskhub-api`).
2. Configure Keycloak audience mapper so mobile access tokens include required audience.
3. Django rejects tokens missing required audience.

### 5.5 Route-level auth split
1. Existing web endpoints continue using current auth stack.
2. All `/api/mobile/v1/*` views explicitly set mobile auth classes and permissions.
3. Mobile views must not rely on global DRF defaults implicitly.

### 5.6 OIDC callback URI contract
1. Canonical iOS redirect URI is `taskhub://oauth/callback`.
2. Keycloak iOS client redirect URI allowlist must include exactly `taskhub://oauth/callback`.
3. iOS app must register URL scheme `taskhub`.
4. Any redirect URI change must be applied in both Keycloak client config and iOS app settings in the same release.

## 6. Backend Data Model Changes

### 6.1 New models in `backend/mobile_api/models.py`
1. `OIDCIdentity`
   - `issuer`, `subject`, `user`, `created_at`, `last_seen_at`.
   - Unique on (`issuer`, `subject`).
2. `MobileDevice`
   - user/org, encrypted APNs token, token hash, app/build/ios metadata, last_seen_at.
   - Unique on (`apns_token_hash`, `apns_environment`).
   - Optional stable `device_installation_id` for deterministic upsert.
3. `NotificationPreference`
   - timezone, quiet hours, reminder offsets, enabled flags.
4. `UserMobilePreference`
   - user/org-scoped app preferences for `/api/mobile/v1/me/preferences`.
   - fields: `default_task_sort`, `show_completed_default`, `start_of_week`, optional widget/task-list display hints.
5. `NotificationDelivery`
   - outbox state, dedupe key, attempts, provider response, timestamps.
   - Worker claim fields: `locked_until`, `locked_by`, `available_at`.
6. `IdempotencyRecord`
   - user, endpoint, idempotency key, canonical request hash, response metadata, TTL lifecycle.

### 6.2 New model in `backend/tasks/models.py`
1. `TaskChangeEvent`
   - id BigAutoField (global monotonic cursor), org, event_type, task_id nullable, payload summary, occurred_at.

### 6.3 Required indexes and constraints
1. `TaskChangeEvent` index on (`org_id`, `id`) for delta sync scans.
2. `NotificationDelivery` index on (`state`, `available_at`) and on (`locked_until`) for worker claim queries.
3. `NotificationDelivery` unique constraint on (`dedupe_key`) for duplicate suppression.
4. `IdempotencyRecord` unique constraint on (`user_id`, `endpoint`, `idempotency_key`) and index on TTL field.
5. `MobileDevice` unique constraint on (`device_installation_id`) when present.

## 7. Mobile API Contract

### 7.1 Discovery
1. `GET /api/mobile/v1/meta`
   - `api_version`
   - `oidc_discovery_url`
   - `oidc_client_id`
   - `required_scopes`
   - `required_audience`
   - sync limits and retention hints

### 7.2 Session/bootstrap
1. `GET /api/mobile/v1/session`
   - resolves Keycloak token to local user/org/role.
   - returns `403 onboarding_required` when no identity mapping exists.

### 7.3 Identity onboarding (admin-only)
1. `POST /api/mobile/v1/admin/identity-links`
2. `DELETE /api/mobile/v1/admin/identity-links/{id}`
3. Full audit trail for all operations.
4. These endpoints are for server admins and migration tooling, not normal iOS app calls.

### 7.4 Functional endpoints
1. `GET/PATCH /api/mobile/v1/me/preferences`
2. `GET /api/mobile/v1/tasks`
3. `GET /api/mobile/v1/tasks/{id}`
4. `POST /api/mobile/v1/tasks` (requires `Idempotency-Key`)
5. `PATCH /api/mobile/v1/tasks/{id}`
6. `DELETE /api/mobile/v1/tasks/{id}`
7. `GET /api/mobile/v1/sync/delta?cursor=<token>&limit=<n>`
8. `POST /api/mobile/v1/devices/register`
9. `PATCH /api/mobile/v1/devices/{id}`
10. `DELETE /api/mobile/v1/devices/{id}`
11. `GET/PATCH /api/mobile/v1/notifications/preferences`
12. `POST /api/mobile/v1/intents/create-task` (requires `Idempotency-Key`)
13. `GET /api/mobile/v1/widget/snapshot`

### 7.5 Standard mobile error envelope
1. All mobile endpoints return errors using the envelope in Section `1.8`.
2. Error `code` values are stable API contract and are covered by OpenAPI in Step `S16`.

### 7.6 Preferences split contract
1. `/api/mobile/v1/me/preferences` uses `UserMobilePreference` and stores app UI defaults.
2. `/api/mobile/v1/notifications/preferences` uses `NotificationPreference` and stores notification timing/quiet-hours behavior.
3. These endpoints must not share a serializer/model implicitly.

## 8. Reverse Proxy and Infrastructure Requirements

### 8.1 nginx updates (mandatory first)
Update `infra/web/nginx.conf`:
1. Add `/api/mobile/v1/` proxy to Django API.
2. Add `/idp/` proxy to Keycloak service.
3. Preserve existing SPA fallback and web/API routes.
4. Forward `Host`, `X-Forwarded-*` headers to API and Keycloak.

### 8.2 Keycloak deployment requirements
1. Local/dev: one Keycloak service in compose.
2. Production reliability target:
   - 2+ Keycloak nodes
   - HA Postgres for Keycloak DB
   - backup/restore runbook
   - health and metrics monitoring

### 8.3 Required Keycloak proxy settings
1. `KC_HTTP_RELATIVE_PATH=/idp`
2. `KC_PROXY_HEADERS=xforwarded`
3. `KC_HOSTNAME=<public-host-or-url>`
4. `KC_HOSTNAME_STRICT=true` (or documented exception)
5. `KC_HEALTH_ENABLED=true`
6. Local dev profile may use `KC_HOSTNAME_STRICT=false`, but production must keep strict hostname validation enabled.

### 8.4 Shared cache and throttling
1. Configure Redis-backed cache for DRF throttles.
2. Do not rely on local-memory throttle storage.

### 8.5 Feature flags
1. `MOBILE_API_ENABLED`
2. `KEYCLOAK_AUTH_ENABLED`
3. `APNS_ENABLED`

## 9. Server Implementation Steps (Execute Here: Server/Backend/Infra)

### [SERVER] Step S0 - Routing and feature-flag preflight
Files to update:
1. `infra/web/nginx.conf`
2. `backend/config/settings.py`
3. `.env.example`
4. `docker-compose.yml`
5. `backend/requirements.in`
6. `backend/requirements.txt`

Tasks:
1. Add `/api/mobile/v1/` and `/idp/` routes.
2. Add feature flags and safe defaults.
3. Add Redis-backed cache config for throttles.
4. Add required backend dependencies for Redis cache and JWT/JWKS verification, then refresh lockfile.

Validation:
```bash
docker compose config >/dev/null
. .venv/bin/activate && pip check
curl -i http://localhost:8080/health/live
```

Run regression gate.

### [SERVER] Step S1 - Keycloak service bootstrap (self-hosted)
Files to update/create:
1. `docker-compose.yml`
2. `.env.example`
3. `docs/keycloak-runbook.md`
4. `tools/keycloak/bootstrap-realm.sh`
5. `tools/keycloak/realm-export/taskhub-realm.json`

Tasks:
1. Add Keycloak service and DB settings.
2. Configure required Keycloak proxy settings.
3. Create realm bootstrap script/import.
4. Add health checks and startup ordering.

Validation:
```bash
docker compose up -d --build
curl -i http://localhost:8080/idp/health/ready
```

Run regression gate.

### [SERVER] Step S2 - Realm, client, audience, and scope automation
Files to update/create:
1. `tools/keycloak/bootstrap-realm.sh`
2. `tools/keycloak/realm-export/taskhub-realm.json`
3. `backend/mobile_api/tests/test_oidc_discovery_contract.py`
4. `tools/keycloak/validate-realm-export.sh`

Tasks:
1. Define realm `taskhub`.
2. Create iOS public client with PKCE and redirect URI allowlist.
3. Set canonical redirect URI to `taskhub://oauth/callback`.
4. Define OIDC + API scopes:
   - `openid`
   - `offline_access`
   - `mobile.read`
   - `mobile.write`
   - `mobile.sync`
   - `mobile.notify`
5. Define API audience and mapper.
6. Make setup idempotent for redeploys.
7. Add deterministic secret-hygiene validator for realm exports.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_oidc_discovery_contract.py
bash tools/keycloak/validate-realm-export.sh tools/keycloak/realm-export/taskhub-realm.json
```

Run regression gate.

### [SERVER] Step S3 - Reverse-proxy OIDC integration tests
Files to create/update:
1. `backend/mobile_api/tests/test_oidc_proxy_integration.py`
2. `docs/keycloak-runbook.md`

Tasks:
1. Verify discovery issuer uses public `/idp` URL through reverse proxy.
2. Verify forwarded host/proto are handled correctly.
3. Verify token `iss` expected by API matches proxied issuer.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_oidc_proxy_integration.py
```

Run regression gate.

### [SERVER] Step S4 - Mobile API scaffold and metadata endpoint
Files to create/update:
1. `backend/mobile_api/apps.py`
2. `backend/mobile_api/urls.py`
3. `backend/mobile_api/views.py`
4. `backend/mobile_api/serializers.py`
5. `backend/config/urls.py`
6. `backend/mobile_api/tests/test_meta_endpoint.py`

Tasks:
1. Create `mobile_api` Django app.
2. Add `/api/mobile/v1/meta` with discovery URL, client ID, required scopes/audience.
3. Enforce host allowlist/canonical host rules.
4. Gate routes with feature flag.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_meta_endpoint.py
curl -i http://localhost:8080/api/mobile/v1/meta
```

Run regression gate.

### [SERVER] Step S5 - JWT validation, route-level auth, and identity linking
Files to create/update:
1. `backend/mobile_api/models.py`
2. `backend/mobile_api/migrations/*`
3. `backend/mobile_api/authentication.py`
4. `backend/mobile_api/permissions.py`
5. `backend/mobile_api/session_views.py`
6. `backend/mobile_api/tests/test_keycloak_jwt_validation.py`

Tasks:
1. Validate tokens via JWKS with soft/hard TTL and unknown-`kid` refresh behavior.
2. Enforce issuer, audience, algorithm allowlist, clock skew bounds, expiry, and scope checks.
3. Implement explicit route-level auth classes for all mobile views.
4. Resolve org membership and role from local DB mapping only (ignore IdP role claims for tenancy auth).
5. Implement `OIDCIdentity` linking and onboarding error behavior.
6. Implement `GET /api/mobile/v1/session`.
7. Implement mobile error envelope + `request_id` for auth/session failures (`onboarding_required`, `invalid_token`, `invalid_audience`, `insufficient_scope`).

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_keycloak_jwt_validation.py
```

Run regression gate.

### [SERVER] Step S6 - Identity onboarding API and audit logging
Files to create/update:
1. `backend/mobile_api/identity_admin_views.py`
2. `backend/mobile_api/identity_admin_serializers.py`
3. `backend/mobile_api/models.py`
4. `backend/mobile_api/migrations/*`
5. `backend/mobile_api/tests/test_identity_onboarding_api.py`

Tasks:
1. Implement admin-only identity link/unlink API.
2. Add audit log table/fields for identity mapping changes.
3. Enforce org and role checks.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_identity_onboarding_api.py
```

Run regression gate.

### [SERVER] Step S7 - User migration and identity backfill
Files to create/update:
1. `tools/keycloak/migrate-users.sh`
2. `tools/keycloak/backfill_oidc_identity.py`
3. `docs/keycloak-runbook.md`
4. `backend/mobile_api/tests/test_identity_backfill.py`

Tasks:
1. Define migration flow for existing Task Hub users to Keycloak.
2. Backfill `OIDCIdentity` mappings safely.
3. Add dry-run mode and verification reports.
4. Define rollback strategy.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_identity_backfill.py
```

Run regression gate.

### [SERVER] Step S8 - Preferences and device registration
Files to create/update:
1. `backend/mobile_api/models.py`
2. `backend/mobile_api/migrations/*`
3. `backend/mobile_api/preferences_views.py`
4. `backend/mobile_api/preferences_serializers.py`
5. `backend/mobile_api/device_views.py`
6. `backend/mobile_api/device_serializers.py`
7. `backend/mobile_api/tests/test_preferences_and_devices.py`

Tasks:
1. Add `UserMobilePreference` for `/api/mobile/v1/me/preferences`.
2. Add `NotificationPreference` with IANA timezone validation.
3. Define precedence rules: user preference overrides org default.
4. Add DST-sensitive quiet-hours tests.
5. Add `MobileDevice` register/update/delete endpoints and ownership/org checks.
6. Implement device upsert semantics keyed by token hash/environment or installation ID.
7. Validate device payload contract fields (`apns_environment`, `device_installation_id`, app/build/iOS metadata).
8. Reject bundle/environment mismatches against APNs server configuration.
9. Add tests that `/me/preferences` and `/notifications/preferences` remain separate contracts.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_preferences_and_devices.py
```

Run regression gate.

### [SERVER] Step S8A - Mobile task CRUD endpoints
Files to create/update:
1. `backend/mobile_api/task_views.py`
2. `backend/mobile_api/task_serializers.py`
3. `backend/mobile_api/urls.py`
4. `backend/mobile_api/tests/test_mobile_task_crud.py`

Tasks:
1. Implement mobile task list/detail/create/update/delete endpoints under `/api/mobile/v1/tasks`.
2. Enforce org-scoped queryset behavior and cross-tenant `404` semantics.
3. Enforce `Idempotency-Key` header requirement for `POST /api/mobile/v1/tasks`.
4. Ensure responses and errors follow the standard mobile error envelope.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_mobile_task_crud.py
```

Run regression gate.

### [SERVER] Step S9 - APNs outbox pipeline
Files to create/update:
1. `backend/mobile_api/models.py`
2. `backend/mobile_api/migrations/*`
3. `backend/mobile_api/apns.py`
4. `backend/mobile_api/notifications.py`
5. `backend/tasks/tasks.py`
6. `backend/mobile_api/tests/test_apns_pipeline.py`
7. `.env.example`

Tasks:
1. Add `NotificationDelivery` outbox.
2. Implement worker-safe claim/lease logic to avoid duplicate sends.
3. Implement enqueue/send/retry/dead-token cleanup jobs.
4. Implement stale-notification cancel/reschedule matrix when due/status changes.
5. Add fail-fast startup checks when `APNS_ENABLED=true` and credentials are invalid.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_apns_pipeline.py
```

Run regression gate.

### [SERVER] Step S10 - Task change event coverage across all mutation paths
Files to create/update:
1. `backend/tasks/models.py`
2. `backend/tasks/migrations/*`
3. `backend/tasks/views.py`
4. `backend/tasks/serializers.py`
5. `backend/tasks/tasks.py`
6. `backend/tasks/email_capture_service.py`
7. `backend/mobile_api/event_emitter.py`
8. `backend/mobile_api/tests/test_task_event_coverage.py`

Tasks:
1. Add `TaskChangeEvent` append-only model.
2. Emit events from all mutation paths:
   - tasks API create/update/delete/reorder
   - recurring task auto-create
   - archive job
   - inbound email ingest
3. Use `TaskChangeEvent.id` as the sync cursor source (no custom per-org sequence allocator).
4. Emit using `transaction.on_commit`.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_task_event_coverage.py
```

Run regression gate.

### [SERVER] Step S11 - Delta sync endpoint
Files to create/update:
1. `backend/mobile_api/sync_views.py`
2. `backend/mobile_api/sync_serializers.py`
3. `backend/mobile_api/tests/test_delta_sync.py`
4. `backend/config/settings.py`

Tasks:
1. Implement `GET /api/mobile/v1/sync/delta`.
2. Enforce `410 cursor_expired` behavior with recovery contract.
3. Add limit bounds and pagination guarantees.
4. Return tombstones and `next_cursor`.
5. Validate cursor against the oldest retained event id for the org to produce deterministic `410` behavior.
6. Return `cursor_expired` in the standard error envelope.
7. Treat cursor input/output as opaque string tokens in serializers and docs.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_delta_sync.py
```

Run regression gate.

### [SERVER] Step S12 - Retention and cleanup jobs
Files to create/update:
1. `backend/mobile_api/cleanup_tasks.py`
2. `backend/tasks/tasks.py`
3. `backend/config/settings.py`
4. `backend/mobile_api/tests/test_retention_cleanup.py`

Tasks:
1. Add scheduled purge for expired `TaskChangeEvent` rows.
2. Add TTL cleanup for `IdempotencyRecord`.
3. Add cleanup/archive policy for old `NotificationDelivery` rows.
4. Ensure purge behavior aligns with sync `410 cursor_expired` contract.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_retention_cleanup.py
```

Run regression gate.

### [SERVER] Step S13 - Idempotency framework
Files to create/update:
1. `backend/mobile_api/models.py`
2. `backend/mobile_api/migrations/*`
3. `backend/mobile_api/idempotency.py`
4. `backend/mobile_api/task_views.py`
5. `backend/mobile_api/intents_views.py`
6. `backend/mobile_api/tests/test_idempotency.py`

Tasks:
1. Add `IdempotencyRecord`.
2. Canonicalize/hash request payload.
3. Replay exact duplicate responses.
4. Return `409 idempotency_conflict` on hash mismatch.
5. Add TTL cleanup task.
6. Enforce transaction-safe upsert behavior under retries/races with DB uniqueness as source of truth.
7. Return `idempotency_conflict` in the standard error envelope.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_idempotency.py
```

Run regression gate.

### [SERVER] Step S14 - Siri and widget endpoints
Files to create/update:
1. `backend/mobile_api/intents_views.py`
2. `backend/mobile_api/intents_serializers.py`
3. `backend/mobile_api/widget_views.py`
4. `backend/mobile_api/widget_serializers.py`
5. `backend/mobile_api/tests/test_intents_and_widget.py`

Tasks:
1. Implement `POST /api/mobile/v1/intents/create-task` with idempotency key requirement.
2. Implement `GET /api/mobile/v1/widget/snapshot` with payload budget and stable ordering.
3. Add cross-tenant 404 tests for mobile routes.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_intents_and_widget.py
```

Run regression gate.

### [SERVER] Step S15 - Observability and security hardening
Files to create/update:
1. `backend/config/settings.py`
2. `backend/mobile_api/throttles.py`
3. `backend/mobile_api/logging.py`
4. `backend/mobile_api/tests/test_mobile_security_guards.py`
5. `backend/mobile_api/tests/test_error_envelope_contract.py`
6. `docs/keycloak-runbook.md`

Tasks:
1. Add route-specific throttles backed by Redis cache.
2. Add request-id structured logs and no-secret logging policy.
3. Add revoked token, insufficient scope, invalid audience, and algorithm mismatch tests.
4. Add envelope-consistency tests for auth/tasks/sync/devices/preferences/intents/widget error responses.
5. Document key rotation and incident handling runbook.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_mobile_security_guards.py backend/mobile_api/tests/test_error_envelope_contract.py
```

Run regression gate.

### [SERVER] Step S16 - OpenAPI and contract freeze
Files to create/update:
1. `backend/mobile_api/schema.py`
2. `backend/mobile_api/tests/test_openapi_schema.py`
3. `docs/mobile-api-contract.md`

Tasks:
1. Generate and publish mobile OpenAPI schema.
2. Add schema diff check in CI.

Validation:
```bash
. .venv/bin/activate
pytest -q backend/mobile_api/tests/test_openapi_schema.py
```

Run regression gate.

### [SERVER] Step S17 - Production HA artifacts and failover validation
Files to create/update:
1. `docs/keycloak-ha-deployment.md`
2. `docs/keycloak-runbook.md`
3. `tools/keycloak/ha-smoke-checks.sh`

Tasks:
1. Produce deployment artifacts/runbook for 2+ Keycloak nodes and HA DB.
2. Define and run failover game-day checks.
3. Capture acceptance criteria and rollback procedures.

Validation:
```bash
bash tools/keycloak/ha-smoke-checks.sh
```

Run regression gate.

## 11. Environment Variables
Add to `.env.example`:
1. `MOBILE_API_ENABLED=true`
2. `KEYCLOAK_AUTH_ENABLED=true`
3. `KEYCLOAK_BASE_URL=http://keycloak:8080/idp`
4. `KEYCLOAK_PUBLIC_BASE_URL=`
5. `KEYCLOAK_REALM=taskhub`
6. `KEYCLOAK_IOS_CLIENT_ID=taskhub-ios`
7. `KEYCLOAK_REQUIRED_AUDIENCE=taskhub-api`
8. `KEYCLOAK_ALLOWED_ALGS=RS256`
9. `KEYCLOAK_JWKS_SOFT_TTL_SECONDS=300`
10. `KEYCLOAK_JWKS_HARD_TTL_SECONDS=3600`
11. `KEYCLOAK_JWKS_FETCH_TIMEOUT_SECONDS=3`
12. `KEYCLOAK_ALLOWED_PUBLIC_HOSTS=`
13. `MOBILE_TOKEN_CLOCK_SKEW_SECONDS=60`
14. `MOBILE_SYNC_MAX_PAGE_SIZE=500`
15. `MOBILE_EVENT_RETENTION_DAYS=30`
16. `MOBILE_IDEMPOTENCY_TTL_HOURS=24`
17. `MOBILE_NOTIFICATION_DELIVERY_RETENTION_DAYS=30`
18. `APNS_ENABLED=false`
19. `APNS_KEY_ID=`
20. `APNS_TEAM_ID=`
21. `APNS_BUNDLE_ID=`
22. `APNS_PRIVATE_KEY_PATH=`
23. `APNS_PRIVATE_KEY_B64=`
24. `APNS_USE_SANDBOX=true`
25. `MOBILE_RATE_LIMIT_AUTH=20/min`
26. `MOBILE_RATE_LIMIT_SYNC=120/min`
27. `MOBILE_RATE_LIMIT_INTENT=30/min`

## 12. End-to-End Validation Gate
Server-only validation:
```bash
docker compose config >/dev/null
. .venv/bin/activate && pytest -q backend
. .venv/bin/activate && pytest -q backend/mobile_api/tests
npm run --prefix frontend build
```

Cross-track integration validation (requires iOS project from `Spec/ios-xcode-app-implementation-plan.md`):
```bash
docker compose config >/dev/null
. .venv/bin/activate && pytest -q backend
. .venv/bin/activate && pytest -q backend/mobile_api/tests
npm run --prefix frontend build
xcodebuild test \
  -project ios/TaskHubMobile.xcodeproj \
  -scheme TaskHubMobile \
  -destination 'platform=iOS Simulator,name=iPhone 16'
```

Manual checks:
1. App URL bootstrap works with same domain as browser.
2. Keycloak login works through `/idp` path on same domain.
3. Mobile task CRUD respects tenancy and permissions.
4. Delta sync reflects API, recurrence, archive, and email-ingest changes.
5. APNs handles retry/cancel/dead-token cleanup correctly.
6. Siri retries do not duplicate tasks.
7. Widget renders with online and offline data.
8. Existing web login/task behavior remains unchanged.

## 13. Rollout Plan
1. Phase 1: deploy with `MOBILE_API_ENABLED=false`.
2. Phase 2: implement and verify identity onboarding API + audit logging in staging.
3. Phase 3: run user migration + identity backfill in staging and generate verification report.
4. Phase 4: run production migration/backfill gate and sampled login verification.
5. Phase 5: enable mobile API + Keycloak auth for internal testing.
6. Phase 6: enable APNs in staging, then production canary.
7. Phase 7: full rollout with dashboards and on-call runbook.
8. Keep feature flags as immediate rollback switches; never disable legacy web auth before mobile auth stabilization.

Track metrics:
1. OIDC login failure rate.
2. Access token validation failure rate.
3. Invalid-audience token rejection rate.
4. Sync lag and cursor-expired rate.
5. APNs failure and dead-token rates.
6. Idempotency conflict rate.

## 14. Definition of Done
1. Keycloak-based PKCE auth works for iOS via same reverse-proxy domain.
2. Mobile API contract is stable, versioned, and schema-published.
3. Delta sync is correct across all task mutation sources.
4. Idempotency safety is enforced with hash conflict protection.
5. APNs pipeline is reliable and observable.
6. Existing web behavior remains backward compatible.
