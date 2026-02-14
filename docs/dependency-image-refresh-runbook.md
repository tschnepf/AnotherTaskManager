# Dependency and Image Refresh Runbook

## Weekly Cadence
1. Pull dependency update PRs (Dependabot/Renovate).
2. Rebuild lockfiles if required.
3. Run full test and security gates.
4. Rebuild container images.

## Commands
```bash
. .venv/bin/activate
pip-compile --upgrade --output-file backend/requirements.txt backend/requirements.in
pip-audit -r backend/requirements.txt
npm update --prefix frontend
npm audit --prefix frontend --audit-level=high
docker compose build --pull
trivy fs --severity HIGH,CRITICAL --exit-code 1 --no-progress .
```

## Emergency Patch Window
- Critical vulnerabilities: patch within 24 hours.
- High vulnerabilities: patch within 72 hours.
