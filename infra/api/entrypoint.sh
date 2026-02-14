#!/usr/bin/env sh
set -eu
python backend/manage.py migrate
exec "$@"
