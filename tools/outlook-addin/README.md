# Task Hub Outlook Add-in (New Outlook for Windows)

This folder contains a web add-in that adds an **Add Task** button in message read view and sends the current message to Task Hub as an `.eml` payload.

## What it does

- Adds a ribbon/action-bar command in new Outlook: **Task Hub -> Add Task**
- Opens a task pane with quick-create fields:
  - Task title (prefilled from email subject)
  - Project (optional)
  - Area (`work`/`personal`, optional)
  - Priority (`1`-`5`, optional)
- Sends the current message to Task Hub inbound capture:
  - `POST /capture/email/inbound`
  - Header: `X-TaskHub-Ingest-Token`
  - Form fields: `email` (`.eml`), `recipient`, optional override fields
- Adds idempotency metadata:
  - `source_origin=outlook_addin`
  - `source_external_id` from Outlook `internetMessageId` when available

## Files

- `manifest.xml`: Outlook add-in manifest (sideload this)
- `taskpane.html`, `taskpane.css`, `taskpane.js`: add-in UI and logic
- `commands.html`: command surface bootstrap file
- `assets/`: add-in icons

## Production hosting (same origin)

In this repo, the web image now copies this folder to `/outlook-addin/*` and rewrites the manifest host at container startup.

Required env var:

- `TASKHUB_PUBLIC_BASE_URL`
  - Example local: `http://localhost:8080`
  - Example production: `https://tasks.example.com`

`manifest.xml` placeholder URLs (`https://taskhub.example.com`) are replaced at runtime with this value.

## Sideload in new Outlook for Windows

1. Open new Outlook.
2. Go to `Settings -> Manage apps` (or `Get Add-ins`).
3. Choose `My add-ins -> Add a custom add-in -> Add from file`.
4. Use manifest URL from your server or upload file:
   - URL: `https://YOUR-TASKHUB-HOST/outlook-addin/manifest.xml`
   - File: `tools/outlook-addin/manifest.xml` (if manually adjusted)

## First run inside Outlook

1. Open any email in read mode.
2. Click `Add Task` from the Task Hub button.
3. Open **Advanced Settings** and enter:
   - Task Hub URL, for example `https://YOUR-HOST`
   - Recipient email matching Task Hub inbound email address
   - Ingest token from Task Hub settings
4. Optionally set title/project/area/priority.
5. Click `Add Current Email`.

## Troubleshooting

- `401`: Missing ingest token header. Save a valid token in Advanced Settings.
- `403`: Invalid token or sender rejected by whitelist.
- `400`: Invalid payload (for example invalid `.eml`, bad area/priority override).
- `429`: Inbound capture throttled; retry after a short delay.
- `Task already exists for this email`: Idempotent replay detected; no duplicate task was created.

## Security notes

- The add-in stores URL/recipient/token in Outlook roaming settings (plus local storage fallback).
- Treat ingest tokens as sensitive and rotate them when needed.
- For this integration, run Task Hub with `INBOUND_EMAIL_MODE=webhook`.
