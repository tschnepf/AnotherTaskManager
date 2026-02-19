# Windows Outlook Headless Automation

This folder contains a one-shot setup script for a mostly unattended Outlook VM.

## What it configures

- Disables sleep and hibernate (AC/DC).
- Applies Windows Update restart-reduction settings.
- Optionally enables Windows auto-logon.
- Creates runtime scripts under `C:\Automation`:
  - `start-outlook.ps1`
  - `start-all.ps1`
  - `watchdog.ps1`
  - `managed-scripts.json` (template)
- Registers scheduled tasks:
  - `TaskHub-StartOutlook`
  - `TaskHub-StartAllScripts`
  - `TaskHub-Watchdog`

## Run

Open an elevated PowerShell prompt and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\\tools\\windows-automation\\setup-headless-outlook-agent.ps1 -ConfigureAutoLogon
```

If your auto-logon account differs from the current user:

```powershell
.\\tools\\windows-automation\\setup-headless-outlook-agent.ps1 `
  -ConfigureAutoLogon `
  -AutomationUser "automation" `
  -AutomationDomain "MYVM" `
  -AutoLogonUser "automation" `
  -AutoLogonDomain "MYVM"
```

Skip optional policy changes if needed:

```powershell
.\\tools\\windows-automation\\setup-headless-outlook-agent.ps1 `
  -SkipPowerSettings `
  -SkipUpdatePolicies
```

## Add your scripts

Edit `C:\Automation\managed-scripts.json`.

Each entry:

```json
{
  "name": "TaskHubAgent",
  "command": "C:\\Python311\\python.exe",
  "arguments": "C:\\Automation\\taskhub-agent.py",
  "workingDirectory": "C:\\Automation",
  "matchPattern": "taskhub-agent.py",
  "enabled": true
}
```

Notes:

- `matchPattern` is used by `start-all.ps1` to detect if the script is already running.
- `enabled` can temporarily disable an entry without deleting it.

## Verify

- Reboot once.
- Confirm user auto-logs in (if configured).
- Confirm Outlook starts.
- Confirm your scripts start.
- Check logs in `C:\Automation\logs`.
