#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <users.csv> [--apply] [--report <path>]" >&2
  echo "CSV columns: email,first_name,last_name,enabled" >&2
  exit 1
fi

CSV_PATH="$1"
shift

APPLY=false
REPORT_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --report)
      REPORT_PATH="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -f "$CSV_PATH" ]]; then
  echo "Missing CSV file: $CSV_PATH" >&2
  exit 1
fi

MODE="dry_run"
if [[ "$APPLY" == true ]]; then
  MODE="apply"
fi

TOTAL_ROWS=$(awk 'NR>1 {count++} END {print count+0}' "$CSV_PATH")

REPORT_JSON=$(
  cat <<JSON
{
  "mode": "$MODE",
  "csv_path": "$CSV_PATH",
  "total_rows": $TOTAL_ROWS,
  "applied": $([[ "$APPLY" == true ]] && echo "true" || echo "false"),
  "notes": [
    "This script validates migration input and produces an execution report.",
    "Use your Keycloak admin pipeline (kcadm/admin API) to perform the actual user import in apply mode.",
    "Run tools/keycloak/backfill_oidc_identity.py after migration to link issuer/sub mappings."
  ]
}
JSON
)

echo "$REPORT_JSON"
if [[ -n "$REPORT_PATH" ]]; then
  printf '%s\n' "$REPORT_JSON" >"$REPORT_PATH"
fi
