# Task Hub

Task Hub is a web app for capturing, organizing, and reviewing tasks across work and personal areas.

## Deploy

### Prerequisites
- Docker + Docker Compose

### 1) Configure environment values
This project currently loads app environment values from `.env.example` in `docker-compose.yml`.

At minimum, update:
- `DJANGO_SECRET_KEY`
- `API_PORT`
- `WEB_PORT`
- `CORS_ALLOWED_ORIGINS` (for your web URL)
- Optional email/AI values if you plan to use those features

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
