#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXPECTED="$ROOT_DIR/backend/mobile_api/openapi/mobile-v1-openapi.json"
TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

PYTHON_BIN="${PYTHON_BIN:-python3}"

(
  cd "$ROOT_DIR/backend"
  "$PYTHON_BIN" - <<'PY'
from mobile_api.schema import render_mobile_openapi_json
print(render_mobile_openapi_json(), end="")
PY
) >"$TMP_FILE"

if ! diff -u "$EXPECTED" "$TMP_FILE"; then
  echo "mobile OpenAPI snapshot is out of date" >&2
  exit 1
fi

echo "mobile OpenAPI snapshot check passed"
