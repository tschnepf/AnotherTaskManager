#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-https://tasks.tardis-proxy.com}"
REALM="${2:-taskhub}"
PROTECTED_PATH="${3:-/api/mobile/v1/tasks}"

DISCOVERY_URL="${BASE_URL%/}/idp/realms/${REALM}/.well-known/openid-configuration"

echo "== Discovery headers =="
curl -sS -I "${DISCOVERY_URL}" | sed -n '1,30p'

echo
echo "== Discovery document (first 50 lines pretty JSON) =="
DISCOVERY_JSON="$(curl -sS -H "Accept: application/json" "${DISCOVERY_URL}")"
echo "${DISCOVERY_JSON}" | jq . | head -n 50

JWKS_URL="$(echo "${DISCOVERY_JSON}" | jq -r '.jwks_uri')"
if [[ -z "${JWKS_URL}" || "${JWKS_URL}" == "null" ]]; then
  echo "ERROR: jwks_uri missing from discovery doc" >&2
  exit 1
fi

echo
echo "== JWKS URL =="
echo "${JWKS_URL}"

echo
echo "== JWKS headers =="
curl -sS -I "${JWKS_URL}" | sed -n '1,30p'

echo
echo "== JWKS document =="
curl -sS -H "Accept: application/json" "${JWKS_URL}" | jq .

echo
echo "== Protected API without token (should remain protected) =="
curl -sS -i "${BASE_URL%/}${PROTECTED_PATH}" | sed -n '1,40p'
