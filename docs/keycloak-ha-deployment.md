# Keycloak HA Deployment

## Topology
1. Run at least 2 Keycloak nodes behind the same reverse proxy (`/idp` path).
2. Use HA Postgres for Keycloak state.
3. Use sticky sessions only if required by your ingress; stateless token validation still occurs in Django.

## Required settings
1. `KC_HTTP_RELATIVE_PATH=/idp`
2. `KC_PROXY_HEADERS=xforwarded`
3. `KC_HOSTNAME=<public-host-or-url>`
4. `KC_HOSTNAME_STRICT=true`
5. `KC_HEALTH_ENABLED=true`

## Operational checks
1. Both nodes report healthy at `/idp/health/ready`.
2. OIDC discovery and JWKS endpoints are reachable via public reverse proxy URL.
3. Mobile API accepts tokens while one Keycloak node is unavailable.

## Failover game-day acceptance
1. Remove one Keycloak node from service.
2. Verify new login flow still works and existing access tokens remain valid.
3. Restore node and verify cluster convergence.
4. Capture latency/error deltas during failover and recovery windows.

## Rollback
1. Scale down to one healthy Keycloak node if cluster instability occurs.
2. Keep legacy web auth active; disable mobile feature flags if required.
3. Restore HA topology after DB and networking issues are resolved.
