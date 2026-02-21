#!/usr/bin/env bash
set -euo pipefail

FILE="${1:-}"
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "Usage: $0 <realm-export.json>" >&2
  exit 1
fi

if rg -n "clientSecret|BEGIN PRIVATE KEY|private_key" "$FILE"; then
  echo "secret-like content found in realm export" >&2
  exit 1
fi

echo "realm export validation passed"
