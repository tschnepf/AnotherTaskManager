#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _configure_django() -> None:
    root = _repo_root()
    backend_dir = root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_SECRET_KEY", "taskhub-backfill-script-local-only")
    os.environ.setdefault("TASKHUB_FIELD_ENCRYPTION_KEY", "taskhub-backfill-script-local-only")
    os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")

    import django

    django.setup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill OIDCIdentity rows from a CSV mapping.")
    parser.add_argument("--csv", required=True, help="CSV path with columns: email,subject[,issuer]")
    parser.add_argument("--issuer", required=True, help="Default issuer when CSV issuer is not provided")
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    parser.add_argument("--report", default="", help="Optional path to write JSON report.")
    args = parser.parse_args()

    _configure_django()

    from mobile_api.backfill import backfill_oidc_identities, load_identity_mapping_csv

    rows = load_identity_mapping_csv(args.csv, default_issuer=args.issuer)
    report = backfill_oidc_identities(rows, dry_run=not args.apply)
    report["mode"] = "apply" if args.apply else "dry_run"

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)

    if args.report:
        Path(args.report).write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
