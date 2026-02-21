#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: link-identities-by-email.sh [options]

Options:
  --apply                     Apply changes (default is dry-run)
  --realm <realm>             Keycloak realm (default: taskhub)
  --issuer <url>              Issuer URL (required)
  --keycloak-container <name> Keycloak container name (default: taskhub-keycloak)
  --api-container <name>      API container name (default: taskhub-api)
  --admin-url <url>           Keycloak admin base URL (default: http://localhost:8080/idp)
  --admin-user <user>         Keycloak admin username (default: KEYCLOAK_ADMIN_USER or admin)
  --admin-password <pass>     Keycloak admin password (default: KEYCLOAK_ADMIN_PASSWORD or admin)
  --report <path>             Write JSON report to file

Example:
  bash tools/keycloak/link-identities-by-email.sh \
    --issuer https://tasks.example.com/idp/realms/taskhub \
    --apply --report /tmp/oidc-link-report.json
USAGE
  exit 1
}

APPLY=false
REALM_NAME="${KEYCLOAK_REALM:-taskhub}"
ISSUER=""
KEYCLOAK_CONTAINER="${KEYCLOAK_CONTAINER:-taskhub-keycloak}"
API_CONTAINER="${API_CONTAINER:-taskhub-api}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
KEYCLOAK_ADMIN_URL="${KEYCLOAK_ADMIN_URL:-http://localhost:8080/idp}"
REPORT_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --realm)
      REALM_NAME="${2:-}"
      shift 2
      ;;
    --issuer)
      ISSUER="${2:-}"
      shift 2
      ;;
    --keycloak-container)
      KEYCLOAK_CONTAINER="${2:-}"
      shift 2
      ;;
    --api-container)
      API_CONTAINER="${2:-}"
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
    --report)
      REPORT_PATH="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

if [[ -z "$ISSUER" ]]; then
  echo "--issuer is required" >&2
  usage
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

kc_exec() {
  docker exec "$KEYCLOAK_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@"
}

MODE="dry_run"
if [[ "$APPLY" == true ]]; then
  MODE="apply"
fi

TMP_RESULTS="$(mktemp)"
TMP_EMAILS="$(mktemp)"
trap 'rm -f "$TMP_RESULTS" "$TMP_EMAILS"' EXIT

TOTAL=0
LINKED=0
WOULD_LINK=0
MISSING_KEYCLOAK=0
FAILED=0

echo "Logging into Keycloak admin API (${KEYCLOAK_ADMIN_URL}) as ${KEYCLOAK_ADMIN_USER}" >&2
kc_exec config credentials \
  --server "$KEYCLOAK_ADMIN_URL" \
  --realm master \
  --user "$KEYCLOAK_ADMIN_USER" \
  --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

docker exec "$API_CONTAINER" python backend/manage.py shell -c '
from core.models import User
for email in User.objects.exclude(email="").values_list("email", flat=True).order_by("email"):
    if email:
        print(email.strip())
' > "$TMP_EMAILS"

while IFS= read -r email; do
  [[ -z "$email" ]] && continue
  TOTAL=$((TOTAL + 1))

  users_json="$(kc_exec get users -r "$REALM_NAME" -q "email=$email" --fields id,email,username 2>/dev/null || true)"
  sub_id="$(jq -r --arg e "$(printf '%s' "$email" | tr '[:upper:]' '[:lower:]')" 'map(select(((.email // .username // "") | ascii_downcase) == $e)) | .[0].id // ""' <<<"$users_json")"

  if [[ -z "$sub_id" ]]; then
    MISSING_KEYCLOAK=$((MISSING_KEYCLOAK + 1))
    jq -nc --arg email "$email" '{email:$email, status:"missing_keycloak_user"}' >>"$TMP_RESULTS"
    continue
  fi

  if [[ "$APPLY" == true ]]; then
    set +e
    out="$(docker exec -e LINK_EMAIL="$email" -e LINK_SUBJECT="$sub_id" -e LINK_ISSUER="$ISSUER" "$API_CONTAINER" python backend/manage.py shell -c '
import os
from core.models import User
from mobile_api.models import OIDCIdentity

email = os.environ["LINK_EMAIL"]
subject = os.environ["LINK_SUBJECT"]
issuer = os.environ["LINK_ISSUER"]

user = User.objects.get(email__iexact=email)
obj, created = OIDCIdentity.objects.update_or_create(
    issuer=issuer,
    subject=subject,
    defaults={"user": user},
)
print("created" if created else "updated")
' 2>&1)"
    rc=$?
    set -e

    if [[ $rc -ne 0 ]]; then
      FAILED=$((FAILED + 1))
      jq -nc --arg email "$email" --arg subject "$sub_id" --arg error "$out" '{email:$email, subject:$subject, status:"error", error:$error}' >>"$TMP_RESULTS"
      continue
    fi
    LINKED=$((LINKED + 1))
    jq -nc --arg email "$email" --arg subject "$sub_id" --arg detail "$out" '{email:$email, subject:$subject, status:"linked", detail:$detail}' >>"$TMP_RESULTS"
  else
    WOULD_LINK=$((WOULD_LINK + 1))
    jq -nc --arg email "$email" --arg subject "$sub_id" '{email:$email, subject:$subject, status:"would_link"}' >>"$TMP_RESULTS"
  fi

done < "$TMP_EMAILS"

REPORT_JSON="$(jq -s \
  --arg mode "$MODE" \
  --arg issuer "$ISSUER" \
  --arg realm "$REALM_NAME" \
  --argjson total "$TOTAL" \
  --argjson linked "$LINKED" \
  --argjson would_link "$WOULD_LINK" \
  --argjson missing "$MISSING_KEYCLOAK" \
  --argjson failed "$FAILED" \
  '{
    mode: $mode,
    issuer: $issuer,
    realm: $realm,
    total_users: $total,
    counts: {
      linked: $linked,
      would_link: $would_link,
      missing_keycloak_user: $missing,
      failed: $failed
    },
    results: .
  }' "$TMP_RESULTS")"

echo "$REPORT_JSON"
if [[ -n "$REPORT_PATH" ]]; then
  printf '%s\n' "$REPORT_JSON" >"$REPORT_PATH"
fi
