# Task Hub

Task Hub is a web app for capturing, organizing, and reviewing tasks across work and personal areas.

## Deploy

### Prerequisites
- Docker + Docker Compose

### 1) Configure environment values
Create a local `.env` file from one of the templates:

```bash
# Local/lab setup:
cp .env.example .env

# Unraid + reverse proxy production setup:
# cp .env.unraid.production.example .env
```

`docker-compose.yml` loads runtime environment values from `.env`.

At minimum, update:
- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS` (comma-separated backend hostnames)
- `API_PORT`
- `WEB_PORT`
- `CORS_ALLOWED_ORIGINS` (for your web URL)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL` (must match)
- Optional email/AI values if you plan to use those features
- `TASKHUB_FIELD_ENCRYPTION_KEY` (required)
- `ATTACHMENT_ACCESS_TOKEN_MAX_AGE_SECONDS` (optional, defaults to 3600)
- `THROTTLE_INBOUND_EMAIL_INGEST` (optional, defaults to `60/min`)

### Field Encryption Key (Required)
The backend will fail fast on startup if neither `TASKHUB_FIELD_ENCRYPTION_KEY` nor
`TASKHUB_FIELD_ENCRYPTION_KEYS` is set to a non-empty value.

Generate a key:
```bash
openssl rand -base64 32
```

Set it in `.env` (or your real deployment env file):
```env
TASKHUB_FIELD_ENCRYPTION_KEY=<paste-generated-key>
```

Optional rotation flow:
- Set `TASKHUB_FIELD_ENCRYPTION_KEYS` as comma-separated keys with the new key first.
- Keep old key(s) after the new key until all data has been rewritten with the new key.

Example:
```env
TASKHUB_FIELD_ENCRYPTION_KEYS=new_key_base64,old_key_base64
```

### Django Secret Key (Required in non-debug)
The backend will fail fast on startup if:
- `DJANGO_SECRET_KEY` is missing while `DJANGO_DEBUG=false`
- `DJANGO_SECRET_KEY` is set to the known unsafe default while `DJANGO_DEBUG=false`
- `DJANGO_SECRET_KEY` is shorter than 32 characters while `DJANGO_DEBUG=false`

Generate a secret key:
```bash
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

Set it in your environment:
```env
DJANGO_SECRET_KEY=<paste-generated-secret>
DJANGO_ALLOWED_HOSTS=your-domain.example.com
```

### Unraid + Reverse Proxy Deployment (Recommended)
Use this flow when TLS is terminated by an existing external nginx reverse proxy:

1. Copy production template and edit values:
```bash
cp .env.unraid.production.example .env
```

2. Generate strong secrets and set in `.env`:
```bash
openssl rand -hex 32   # DJANGO_SECRET_KEY
openssl rand -hex 32   # TASKHUB_FIELD_ENCRYPTION_KEY
```

3. Set these `.env` values for your domain:
- `DJANGO_ALLOWED_HOSTS=tasks.example.com`
- `CORS_ALLOWED_ORIGINS=https://tasks.example.com`
- `AUTH_COOKIE_SECURE=true`
- `CSRF_COOKIE_SECURE=true`
- `WEB_PORT=8080` (or another internal host port)
- `API_PORT=127.0.0.1:8001` (optional hardening if only local access is needed)

4. Start the stack:
```bash
docker compose up -d --build
```

5. Configure external nginx reverse proxy to route your public domain to the Task Hub web container host port (`http://<unraid-host-ip>:8080`), and forward headers:
```nginx
server {
    listen 443 ssl;
    server_name tasks.example.com;

    location / {
        proxy_pass http://UNRAID_HOST_IP:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }
}
```

6. Verify:
```bash
curl -i https://tasks.example.com/health/live
```

If you recreate `api` and briefly see `502` from the `web` container, restart `web` once:
```bash
docker compose restart web
```

### 2) Start the app
```bash
docker compose up -d --build
```

Optional: include local AI container
```bash
docker compose --profile local-ai up -d --build
```

### 3) Confirm services are running
```bash
docker compose ps
```

Open the app at:
- `http://localhost:8080` (or your configured `WEB_PORT`)

## First-Time Setup

The UI starts at a login page. Create the first account once via API:

```bash
curl -X POST http://localhost:8080/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "owner@example.com",
    "password": "StrongPass123!",
    "display_name": "Owner",
    "organization_name": "My Organization"
  }'
```

Then sign in from the web app with that email/password.

## How To Use Task Hub

### Daily task flow
- Use **Quick add** to create tasks (title, work/personal area, priority, project).
- Use the left sidebar to switch views: **All**, **Work**, **Personal**, and project-specific views.
- Mark tasks complete with the checkbox.
- Reorder tasks by dragging the grip handle.
- Open task details to add notes and upload attachments.
- Use the minus/delete action to remove a task.

### Settings
Open **Settings** from the sidebar.

Available sections:
- **User**: display name, reply-to email, timezone
- **IMAP**: incoming email import settings and manual sync
- **AI And Privacy**: AI mode (`off`, `local`, `cloud`, `hybrid`) and privacy options
- **Task List**: default landing view and grouping behavior
- **Backup & Restore**: download full JSON backup and restore from backup file

### Incoming email capture
Mode is controlled by `INBOUND_EMAIL_MODE`:
- `imap`: configure IMAP credentials in Settings, then sync manually or on schedule
- `gmail_oauth`: connect Gmail from Settings and sync
- `webhook`: use `/capture/email/inbound` with header `X-TaskHub-Ingest-Token`

When using webhook mode, rotate the ingest token from Settings and store it immediately.
For security, the token is only returned when newly rotated/generated.

Example webhook upload:
```bash
curl -X POST http://localhost:8080/capture/email/inbound \
  -H "X-TaskHub-Ingest-Token: <your_ingest_token>" \
  -F "recipient=tasks@yourdomain.com" \
  -F "email=@/path/to/message.eml"
```

### Backup and restore
- Go to **Settings -> Backup & Restore**
- **Download Backup** to export current data
- To restore, upload a backup file and type `RESTORE` to confirm
- After restore, sign in again

## Stop The App

```bash
docker compose down
```
