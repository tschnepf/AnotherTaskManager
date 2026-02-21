#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8080}"
REALM="${KEYCLOAK_REALM:-taskhub}"

echo "Checking Keycloak readiness at ${BASE_URL}/idp/health/ready"
curl -fsS "${BASE_URL}/idp/health/ready" >/dev/null

echo "Checking OIDC discovery for realm ${REALM}"
curl -fsS "${BASE_URL}/idp/realms/${REALM}/.well-known/openid-configuration" >/dev/null

echo "Checking JWKS endpoint"
curl -fsS "${BASE_URL}/idp/realms/${REALM}/protocol/openid-connect/certs" >/dev/null

echo "HA smoke checks passed"
