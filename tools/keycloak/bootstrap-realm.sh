#!/usr/bin/env bash
set -euo pipefail

REALM_FILE="$(dirname "$0")/realm-export/taskhub-realm.json"
KEYCLOAK_CONTAINER="${KEYCLOAK_CONTAINER:-keycloak}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
KEYCLOAK_ADMIN_URL="${KEYCLOAK_ADMIN_URL:-http://localhost:8080/idp}"
REALM_NAME="${KEYCLOAK_REALM:-taskhub}"

if [[ ! -f "$REALM_FILE" ]]; then
  echo "Missing realm export: $REALM_FILE" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

echo "Validating export hygiene"
bash "$(dirname "$0")/validate-realm-export.sh" "$REALM_FILE"

echo "Waiting for Keycloak admin endpoint at $KEYCLOAK_ADMIN_URL"
until curl -fsS "$KEYCLOAK_ADMIN_URL/health/ready" >/dev/null; do
  sleep 2
done

echo "Logging into Keycloak via kcadm (container: $KEYCLOAK_CONTAINER)"
docker exec "$KEYCLOAK_CONTAINER" /opt/keycloak/bin/kcadm.sh config credentials \
  --server "$KEYCLOAK_ADMIN_URL" \
  --realm master \
  --user "$KEYCLOAK_ADMIN_USER" \
  --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

if docker exec "$KEYCLOAK_CONTAINER" /opt/keycloak/bin/kcadm.sh get "realms/${REALM_NAME}" >/dev/null 2>&1; then
  echo "Realm ${REALM_NAME} already exists; updating import payload for idempotent reapply"
  docker cp "$REALM_FILE" "${KEYCLOAK_CONTAINER}:/tmp/taskhub-realm.json"
  docker exec "$KEYCLOAK_CONTAINER" /opt/keycloak/bin/kcadm.sh update "realms/${REALM_NAME}" -f /tmp/taskhub-realm.json >/dev/null
else
  echo "Creating realm ${REALM_NAME} from export"
  docker cp "$REALM_FILE" "${KEYCLOAK_CONTAINER}:/tmp/taskhub-realm.json"
  docker exec "$KEYCLOAK_CONTAINER" /opt/keycloak/bin/kcadm.sh create realms -f /tmp/taskhub-realm.json >/dev/null
fi

echo "Realm bootstrap complete"
