#!/bin/sh
set -eu

manifest_path="/usr/share/nginx/html/outlook-addin/manifest.xml"
public_base_url="${TASKHUB_PUBLIC_BASE_URL:-}"

if [ -n "$public_base_url" ] && [ -f "$manifest_path" ]; then
  normalized_base_url="$(printf '%s' "$public_base_url" | sed -e 's/[[:space:]]*$//' -e 's#/*$##')"
  escaped_base_url="$(printf '%s' "$normalized_base_url" | sed -e 's/[\\/&]/\\&/g')"
  sed -i "s#https://taskhub.example.com#${escaped_base_url}#g" "$manifest_path"
else
  echo "TASKHUB_PUBLIC_BASE_URL not set or manifest missing; skipping Outlook manifest URL substitution." >&2
fi

exec "$@"
