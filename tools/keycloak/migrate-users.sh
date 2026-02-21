#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: migrate-users.sh <users.csv> [options]

CSV columns (header required):
  email,first_name,last_name,enabled[,password]

Options:
  --apply                     Apply changes (default is dry-run)
  --report <path>             Write JSON report to file
  --realm <realm>             Keycloak realm (default: taskhub)
  --keycloak-container <name> Keycloak container name (default: taskhub-keycloak)
  --admin-url <url>           Keycloak admin base URL (default: http://localhost:8080/idp)
  --admin-user <user>         Keycloak admin username (default: KEYCLOAK_ADMIN_USER or admin)
  --admin-password <pass>     Keycloak admin password (default: KEYCLOAK_ADMIN_PASSWORD or admin)
  --update-existing           Update first/last/enabled for existing users
  --set-password              Set passwords from CSV password column or --default-password
  --default-password <pass>   Fallback password if CSV password is empty
  --temporary-password        Mark set password as temporary (change on first login)

Examples:
  bash tools/keycloak/migrate-users.sh users.csv
  bash tools/keycloak/migrate-users.sh users.csv --apply --set-password --default-password 'TempPass123!' --temporary-password
USAGE
  exit 1
}

if [[ $# -lt 1 ]]; then
  usage
fi

CSV_PATH="$1"
shift

APPLY=false
REPORT_PATH=""
REALM_NAME="${KEYCLOAK_REALM:-taskhub}"
KEYCLOAK_CONTAINER="${KEYCLOAK_CONTAINER:-taskhub-keycloak}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
KEYCLOAK_ADMIN_URL="${KEYCLOAK_ADMIN_URL:-http://localhost:8080/idp}"
UPDATE_EXISTING=false
SET_PASSWORD=false
DEFAULT_PASSWORD=""
TEMP_PASSWORD=false

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
    --realm)
      REALM_NAME="${2:-}"
      shift 2
      ;;
    --keycloak-container)
      KEYCLOAK_CONTAINER="${2:-}"
      shift 2
      ;;
    --admin-url)
      KEYCLOAK_ADMIN_URL="${2:-}"
      shift 2
      ;;
    --admin-user)
      KEYCLOAK_ADMIN_USER="${2:-}"
      shift 2
      ;;
    --admin-password)
      KEYCLOAK_ADMIN_PASSWORD="${2:-}"
      shift 2
      ;;
    --update-existing)
      UPDATE_EXISTING=true
      shift
      ;;
    --set-password)
      SET_PASSWORD=true
      shift
      ;;
    --default-password)
      DEFAULT_PASSWORD="${2:-}"
      shift 2
      ;;
    --temporary-password)
      TEMP_PASSWORD=true
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [[ ! -f "$CSV_PATH" ]]; then
  echo "Missing CSV file: $CSV_PATH" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

trim() {
  local val="$1"
  val="${val%$'\r'}"
  # shellcheck disable=SC2001
  val="$(echo "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  printf '%s' "$val"
}

normalize_bool() {
  local raw
  raw="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$raw" in
    ""|1|true|yes|y) printf 'true' ;;
    0|false|no|n) printf 'false' ;;
    *) printf 'true' ;;
  esac
}

kc_exec() {
  docker exec "$KEYCLOAK_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@"
}

if [[ "${KEYCLOAK_ADMIN_PASSWORD}" == "" ]]; then
  echo "Keycloak admin password cannot be empty" >&2
  exit 1
fi

MODE="dry_run"
if [[ "$APPLY" == true ]]; then
  MODE="apply"
fi

TMP_RESULTS="$(mktemp)"
trap 'rm -f "$TMP_RESULTS"' EXIT

TOTAL_ROWS=0
CREATED=0
UPDATED=0
EXISTS=0
FAILED=0
PASSWORD_SET=0
PASSWORD_SKIPPED=0

echo "Logging into Keycloak admin API (${KEYCLOAK_ADMIN_URL}) as ${KEYCLOAK_ADMIN_USER}" >&2
kc_exec config credentials \
  --server "$KEYCLOAK_ADMIN_URL" \
  --realm master \
  --user "$KEYCLOAK_ADMIN_USER" \
  --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

# Validate header
HEADER="$(head -n 1 "$CSV_PATH" | tr -d '\r')"
case "$HEADER" in
  email,first_name,last_name,enabled|email,first_name,last_name,enabled,password) ;;
  *)
    echo "Unexpected CSV header: $HEADER" >&2
    echo "Expected: email,first_name,last_name,enabled[,password]" >&2
    exit 1
    ;;
esac

while IFS=',' read -r raw_email raw_first raw_last raw_enabled raw_password _rest; do
  email="$(trim "${raw_email:-}")"
  first_name="$(trim "${raw_first:-}")"
  last_name="$(trim "${raw_last:-}")"
  enabled="$(normalize_bool "$(trim "${raw_enabled:-}")")"
  csv_password="$(trim "${raw_password:-}")"

  if [[ -z "$email" ]]; then
    continue
  fi

  TOTAL_ROWS=$((TOTAL_ROWS + 1))

  existing_json="$(kc_exec get users -r "$REALM_NAME" -q "email=$email" --fields id,email,username,enabled 2>/dev/null || true)"
  existing_id="$(jq -r --arg e "$(printf '%s' "$email" | tr '[:upper:]' '[:lower:]')" 'map(select(((.email // .username // "") | ascii_downcase) == $e)) | .[0].id // ""' <<<"$existing_json")"

  action=""
  status="ok"
  message=""
  user_id="$existing_id"

  if [[ -z "$existing_id" ]]; then
    action="create"
    if [[ "$APPLY" == true ]]; then
      create_args=(create users -r "$REALM_NAME" -s "username=$email" -s "email=$email" -s "enabled=$enabled")
      if [[ -n "$first_name" ]]; then
        create_args+=(-s "firstName=$first_name")
      fi
      if [[ -n "$last_name" ]]; then
        create_args+=(-s "lastName=$last_name")
      fi

      set +e
      created_id="$(kc_exec "${create_args[@]}" -i 2>&1)"
      rc=$?
      set -e
      if [[ $rc -ne 0 ]]; then
        FAILED=$((FAILED + 1))
        status="error"
        message="$created_id"
        jq -nc \
          --arg email "$email" \
          --arg action "$action" \
          --arg status "$status" \
          --arg message "$message" \
          '{email:$email, action:$action, status:$status, message:$message}' >>"$TMP_RESULTS"
        continue
      fi
      user_id="$(printf '%s' "$created_id" | tr -d '\r\n')"
      CREATED=$((CREATED + 1))
      message="created"
    else
      CREATED=$((CREATED + 1))
      message="would_create"
    fi
  else
    if [[ "$UPDATE_EXISTING" == true ]]; then
      action="update"
      if [[ "$APPLY" == true ]]; then
        kc_exec update "users/$existing_id" -r "$REALM_NAME" \
          -s "firstName=$first_name" \
          -s "lastName=$last_name" \
          -s "enabled=$enabled" >/dev/null
        message="updated"
      else
        message="would_update"
      fi
      UPDATED=$((UPDATED + 1))
    else
      action="exists"
      EXISTS=$((EXISTS + 1))
      message="already_exists"
    fi
  fi

  if [[ "$SET_PASSWORD" == true ]]; then
    candidate_password="$csv_password"
    if [[ -z "$candidate_password" ]]; then
      candidate_password="$DEFAULT_PASSWORD"
    fi

    if [[ -n "$candidate_password" ]]; then
      if [[ "$APPLY" == true ]]; then
        pass_args=(set-password -r "$REALM_NAME" --userid "$user_id" --new-password "$candidate_password")
        if [[ "$TEMP_PASSWORD" == true ]]; then
          pass_args+=(--temporary)
        fi
        kc_exec "${pass_args[@]}" >/dev/null
      fi
      PASSWORD_SET=$((PASSWORD_SET + 1))
    else
      PASSWORD_SKIPPED=$((PASSWORD_SKIPPED + 1))
    fi
  fi

  jq -nc \
    --arg email "$email" \
    --arg action "$action" \
    --arg status "$status" \
    --arg user_id "$user_id" \
    --arg message "$message" \
    '{email:$email, action:$action, status:$status, user_id:($user_id|select(length>0)?), message:$message}' >>"$TMP_RESULTS"
done < <(tail -n +2 "$CSV_PATH")

REPORT_JSON="$(jq -s \
  --arg mode "$MODE" \
  --arg csv_path "$CSV_PATH" \
  --argjson total_rows "$TOTAL_ROWS" \
  --argjson created "$CREATED" \
  --argjson updated "$UPDATED" \
  --argjson exists "$EXISTS" \
  --argjson failed "$FAILED" \
  --argjson password_set "$PASSWORD_SET" \
  --argjson password_skipped "$PASSWORD_SKIPPED" \
  '{
    mode: $mode,
    csv_path: $csv_path,
    total_rows: $total_rows,
    applied: ($mode == "apply"),
    counts: {
      created: $created,
      updated: $updated,
      exists: $exists,
      failed: $failed,
      password_set: $password_set,
      password_skipped: $password_skipped
    },
    results: .
  }' "$TMP_RESULTS")"

echo "$REPORT_JSON"

if [[ -n "$REPORT_PATH" ]]; then
  printf '%s\n' "$REPORT_JSON" >"$REPORT_PATH"
fi
