# Task Hub iOS App Implementation Plan (Xcode Execution Track)

This document is the iOS/Xcode execution track split from `Spec/ios-mobile-implementation-plan.md`.

## Goal
Deliver a production-ready iOS app that connects to self-hosted Task Hub and supports:
1. User-entered server URL bootstrap.
2. Keycloak OAuth/OIDC login via PKCE.
3. Task sync via mobile API delta cursor model.
4. APNs registration and notification preferences.
5. Siri task creation and home-screen widget data.

## 0. Ownership and Dependency Boundary
1. This file is for Xcode/iOS app execution only.
2. Server/backend/infra work is defined in `Spec/ios-server-implementation-plan.md`.
3. iOS implementation depends on server track completion for:
   - `/health/live`
   - `/api/mobile/v1/meta`
   - `/api/mobile/v1/session`
   - `/api/mobile/v1/tasks`
   - `/api/mobile/v1/tasks/{id}`
   - `/api/mobile/v1/sync/delta`
   - `/api/mobile/v1/me/preferences`
   - `/api/mobile/v1/notifications/preferences`
   - `/api/mobile/v1/devices/register`
   - `/api/mobile/v1/devices/{id}`
   - `/api/mobile/v1/intents/create-task`
   - `/api/mobile/v1/widget/snapshot`

## 1. Required Server Contracts (Consumed by iOS)
1. iOS user enters one Task Hub base URL (same host as browser).
2. Keycloak is exposed at `/idp` behind the same reverse proxy domain.
3. `GET /api/mobile/v1/meta` returns:
   - `api_version`
   - `oidc_discovery_url`
   - `oidc_client_id`
   - `required_scopes`
   - `required_audience`
4. `GET /api/mobile/v1/session` may return `403 onboarding_required` for unmapped identities.
5. Create endpoints requiring idempotency must accept `Idempotency-Key`.
6. Delta sync contract must support `410 cursor_expired` with full-resync behavior.
7. Canonical OIDC redirect URI is `taskhub://oauth/callback` and must match Keycloak client allowlist exactly.
8. App must register URL scheme `taskhub` for OIDC callback handling.
9. Mobile API errors use the stable envelope:
   - `{"error":{"code":"<machine_code>","message":"<human_message>","details":{}},"request_id":"<id>"}`
10. iOS must branch on `error.code` (not message), especially:
   - `onboarding_required`
   - `cursor_expired`
   - `idempotency_conflict`
   - `insufficient_scope`
   - `invalid_audience`
   - `invalid_token`
11. APNs contract:
   - app bundle identifier must match server `APNS_BUNDLE_ID`
   - device registration sends `apns_environment` as `sandbox` or `production`
   - device registration includes stable `device_installation_id`

12. Identity onboarding endpoints under `/api/mobile/v1/admin/identity-links` and `/api/mobile/v1/admin/identity-links/{id}` are admin-only and are not called by the iOS client.
13. Sync cursor is an opaque string token; iOS must store/forward it without parsing.
14. `/api/mobile/v1/me/preferences` is for app UI defaults; `/api/mobile/v1/notifications/preferences` is for notification timing/quiet hours.
15. App + widget + intents share:
   - base URL + non-secret cache in App Group storage
   - auth tokens via shared Keychain Access Group
   - no interactive auth flows inside widget/intents extensions

## 2. iOS Prerequisites
1. Xcode 15+ with iOS 17 SDK.
2. Apple Developer account configured for signing.
3. App Groups and Keychain Sharing entitlements available.
4. APNs capability enabled for app target.

## 3. First-Time Xcode Setup (If You Have Not Used Xcode Before)
Use this once before starting Step I0-I5.

1. Install Xcode from the Mac App Store.
2. Open Xcode once and allow it to install any required components.
3. In Xcode, go to `Xcode > Settings > Accounts` and sign in with your Apple ID.
4. Verify command line tools:
   - `Xcode > Settings > Locations > Command Line Tools`
   - choose the latest installed Xcode version in the dropdown.
5. Open this repository folder in Finder and create an `ios/` folder if it does not already exist.
6. In Xcode, choose `File > New > Project...` and create:
   - iOS App (SwiftUI, Swift, iOS 17.0+)
   - Product Name: `TaskHubMobile`
   - Organization Identifier: your reverse-DNS id (example: `com.tim`)
   - Interface: SwiftUI
   - Testing: enable unit tests and UI tests
   - save the project under `ios/` so the project path is `ios/TaskHubMobile.xcodeproj`.
7. In project settings, set Signing for Debug:
   - choose your Team
   - keep automatic signing enabled
   - confirm the bundle identifier is unique in your Apple account.
8. Add one iOS Simulator locally:
   - `Xcode > Settings > Platforms` (install iOS runtime if prompted)
   - `Window > Devices and Simulators` and ensure an iPhone simulator exists (for example iPhone 16).
9. Run the app once in simulator (`Cmd+R`) and confirm it builds and launches.
10. Optional terminal check from repo root:
```bash
xcodebuild -project ios/TaskHubMobile.xcodeproj -scheme TaskHubMobile -destination 'platform=iOS Simulator,name=iPhone 16' build
```

## 4. iOS Scaffold Steps (Execute in Xcode)

### [XCODE] Step I0 - Server URL bootstrap
Xcode AI prompt:
```text
Create first-launch server setup UI that asks for Task Hub base URL.
Rules:
- require https URL
- normalize trailing slash
- validate GET /health/live and GET /api/mobile/v1/meta
- persist URL after successful validation
- show actionable errors on failure
Use this base URL for all app calls.
```

### [XCODE] Step I1 - Project and targets
Xcode AI prompt:
```text
Using existing iOS SwiftUI app TaskHubMobile (iOS 17+), add and configure targets.
Add targets:
- TaskHubMobile
- TaskHubWidgetExtension
- TaskHubIntentsExtension
- TaskHubNotificationServiceExtension
Enable App Groups and Keychain Sharing.
Define and use one App Group identifier and one shared Keychain access group across all targets.
Persist base URL in App Group storage.
Persist tokens in shared Keychain access group.
```

### [XCODE] Step I2 - Keycloak PKCE auth integration
Xcode AI prompt:
```text
Implement OIDC Authorization Code + PKCE using ASWebAuthenticationSession.
Read OIDC discovery URL/client ID/scopes/audience from GET /api/mobile/v1/meta.
Use discovery endpoints for authorize/token/revoke.
Use redirect URI taskhub://oauth/callback.
Request scopes including openid and offline_access.
Store tokens in Keychain.
Implement refresh and logout.
Handle onboarding_required using error.code from API error envelope and show onboarding instruction UI.
On invalid_token (401), perform one refresh attempt then retry the original request once before forcing re-auth.
```

### [XCODE] Step I3 - API client and sync
Xcode AI prompt:
```text
Build typed API client for /api/mobile/v1 endpoints.
Implement SyncEngine with cursor delta sync.
Handle 410 cursor_expired by full resync.
Persist cursor only after successful local transaction.
Treat cursor as opaque string token; never parse it as an integer.
For every POST /api/mobile/v1/tasks request include Idempotency-Key.
Handle idempotency_conflict using error.code and retry-safe UX.
For 401 invalid_token on API calls: refresh token once, replay request once, then surface signed-out state if still unauthorized.
```

### [XCODE] Step I4 - Push, Siri, widget
Xcode AI prompt:
```text
Implement:
1) APNs registration + /api/mobile/v1/devices/register and /api/mobile/v1/devices/{id}
2) Send device payload with apns_environment, stable device_installation_id, app/build metadata, iOS version, timezone
3) Ensure app bundle id/APNs environment matches server APNS_BUNDLE_ID and deployment environment
4) Preferences UI for /api/mobile/v1/notifications/preferences and /api/mobile/v1/me/preferences
5) CreateTaskIntent calling /api/mobile/v1/intents/create-task with Idempotency-Key
6) Widget snapshot cache from /api/mobile/v1/widget/snapshot in App Group
7) Ensure widget and intents use shared App Group + shared Keychain state and never trigger interactive login
```

### [XCODE] Step I5 - Tests
Xcode AI prompt:
```text
Add tests for:
- server URL bootstrap
- auth state + token refresh
- onboarding_required handling
- sync cursor recovery
- idempotency header generation for POST /api/mobile/v1/tasks and /api/mobile/v1/intents/create-task
- error envelope parsing by error.code
- invalid_token refresh-once + retry-once behavior
- shared App Group/Keychain state access across app, widget, and intents
- Siri idempotency request builder
- widget cache rendering
Add UI smoke tests for login and task list.
```

## 5. Xcode Validation
```bash
xcodebuild test \
  -project ios/TaskHubMobile.xcodeproj \
  -scheme TaskHubMobile \
  -destination 'platform=iOS Simulator,name=iPhone 16'
```

## 6. Cross-Track Integration Validation
Run after server and iOS tracks are both implemented.

Manual checks:
1. App URL bootstrap works with same domain as browser.
2. Keycloak login works through `/idp` path on same domain.
3. Mobile task CRUD respects tenancy and permissions.
4. Delta sync reflects API, recurrence, archive, and email-ingest changes.
5. APNs handles retry/cancel/dead-token cleanup correctly.
6. Siri retries do not duplicate tasks.
7. Widget renders with online and offline data.
8. Existing web login/task behavior remains unchanged.

## 7. Release Gating
1. Do not ship beyond internal testing until server rollout phases 1-4 in `Spec/ios-server-implementation-plan.md` are complete.
2. Do not enable production push notifications in the app until server rollout phase 6 is complete.
3. Public iOS rollout must be gated on successful cross-track validation and server phase 7 readiness.

## 8. iOS Definition of Done
1. PKCE login works against self-hosted Keycloak via reverse-proxied `/idp`.
2. Token storage/refresh/logout behavior is stable and tested.
3. Sync engine correctly handles normal delta flow and `410 cursor_expired` recovery.
4. Siri task creation is idempotent under retries.
5. Widget uses cached snapshot and renders offline.
