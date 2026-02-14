# Dependency Security Checklist (Django/Node/Docker)

## Purpose
Use this checklist to keep dependencies and container images current, supported, and free of known high-risk vulnerabilities.

## Hard Rules
1. Use latest stable releases only (no pre-release/beta/rc packages in production).
2. Keep all runtime dependencies locked and committed (lockfiles are required).
3. Block merge/release on any `HIGH` or `CRITICAL` vulnerability in app deps or images.
4. Run dependency and image update checks weekly.
5. Apply security fixes immediately when advisories are published.

## Lockfile Requirements
- Backend: keep `backend/requirements.in` and generated `backend/requirements.txt` in source control.
- Frontend: keep `frontend/package-lock.json` in source control.
- Build/deploy from lockfiles only.

## Bootstrap Commands (Initial Setup)
### Backend (Python)
```bash
cd backend
python -m pip install --upgrade pip
pip install pip-tools pip-audit
# define top-level deps in requirements.in, then resolve to latest stable:
pip-compile --upgrade requirements.in
pip-sync requirements.txt
pip-audit -r requirements.txt
```

### Frontend (Node)
```bash
cd frontend
npm install
npm audit --audit-level=high
```

### Container Images
```bash
# pull latest stable major/minor tags approved for the project
docker pull postgres:17
docker pull redis:7
docker pull nginx:1.27

# scan built images (example)
trivy image --severity HIGH,CRITICAL --exit-code 1 taskhub-api:dev
```

## CI Required Checks
Run on every PR and main branch push:
```bash
pip-audit -r backend/requirements.txt
npm audit --prefix frontend --audit-level=high
trivy fs --severity HIGH,CRITICAL --exit-code 1 .
```

Reference workflow:
- `.github/workflows/dependency-security.yml` implements these checks in CI.

CI policy:
- Fail pipeline on any `HIGH`/`CRITICAL` findings.
- Do not bypass without documented risk acceptance and an expiry date.

## Weekly Maintenance
1. Run automated update bot (Dependabot or Renovate) weekly.
2. Merge safe patch/minor updates after tests and scans pass.
3. Review major upgrades and schedule compatibility testing.
4. Rebuild images to pick up base OS security patches.

## Incident Response for New CVEs
1. Identify affected package/image and impacted service.
2. Patch to fixed version or mitigate within 24 hours for `CRITICAL`, 72 hours for `HIGH`.
3. Re-run full CI security scans.
4. Record remediation in release notes/changelog.

## Definition of Done (Security)
- Dependencies and images are on latest stable supported versions.
- Lockfiles are updated and committed.
- CI security checks pass with zero `HIGH`/`CRITICAL`.
- Any temporary exception is documented with owner and expiry date.
