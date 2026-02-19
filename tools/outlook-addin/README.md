# Task Hub Outlook Add-in (New Outlook for Windows)

This folder contains a web add-in that adds an **Add Task** button in message read view and sends the current message to Task Hub as an `.eml` payload.

## What it does

- Adds a ribbon/action-bar command in new Outlook: **Task Hub -> Add Task**
- Opens a task pane with:
  - Task Hub URL
  - Inbound recipient email
  - Inbound ingest token
- Persists settings in Outlook roaming settings (plus local storage fallback), so you do not re-enter them each time.
- Calls Task Hub inbound capture:
  - `POST /capture/email/inbound`
  - Header: `X-TaskHub-Ingest-Token`
  - Form fields: `email` (`.eml`), `recipient`, optional `sender`

## Files

- `manifest.xml`: Outlook add-in manifest (sideload this)
- `taskpane.html`, `taskpane.css`, `taskpane.js`: add-in UI and logic
- `commands.html`: command surface bootstrap file
- `assets/`: add-in icons

## Before sideloading

1. Host this folder over HTTPS (required by Outlook add-ins).
2. Replace `https://taskhub.example.com` in `manifest.xml` with your HTTPS host.

Example replacement:

```bash
perl -pi -e 's#https://taskhub\\.example\\.com#https://YOUR-HOST#g' tools/outlook-addin/manifest.xml
```

## Sideload in new Outlook for Windows

1. Open new Outlook.
2. Go to `Settings -> Manage apps` (or `Get Add-ins`).
3. Choose `My add-ins -> Add a custom add-in -> Add from file`.
4. Select `tools/outlook-addin/manifest.xml`.

## First run inside Outlook

1. Open any email.
2. Click `Add Task` from the Task Hub button.
3. Enter:
   - Task Hub URL, for example `https://YOUR-HOST`
   - Recipient email matching Task Hub inbound email address
   - Ingest token from Task Hub settings
4. Click `Save Settings`.
5. Click `Add Current Email`.

## Notes

- The add-in stores your ingest token in Outlook roaming settings. Treat that token as sensitive.
- If Task Hub is on a different origin than the add-in host, configure CORS accordingly.
