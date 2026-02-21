#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <output.csv> [--api-container <name>]" >&2
  exit 1
fi

OUT_PATH="$1"
shift
API_CONTAINER="${API_CONTAINER:-taskhub-api}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-container)
      API_CONTAINER="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT_PATH")"

docker exec "$API_CONTAINER" python backend/manage.py shell -c '
import csv
import sys
from core.models import User

writer = csv.writer(sys.stdout)
writer.writerow(["email", "first_name", "last_name", "enabled"])
for user in User.objects.order_by("email").iterator():
    email = (user.email or "").strip()
    if not email:
        continue
    writer.writerow([
        email,
        (user.first_name or "").strip(),
        (user.last_name or "").strip(),
        "true" if user.is_active else "false",
    ])
' > "$OUT_PATH"

echo "Wrote $(wc -l < "$OUT_PATH") lines to $OUT_PATH"
