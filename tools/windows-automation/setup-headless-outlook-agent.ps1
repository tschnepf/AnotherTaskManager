#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$AutomationRoot = "C:\Automation",
  [string]$TaskPrefix = "TaskHub",
  [string]$AutomationUser = $env:USERNAME,
  [string]$AutomationDomain = $env:COMPUTERNAME,
  [int]$OutlookDelaySeconds = 45,
  [int]$ScriptsDelaySeconds = 90,
  [int]$WatchdogLogonDelaySeconds = 120,
  [ValidateRange(1, 59)]
  [int]$WatchdogIntervalMinutes = 5,
  [ValidateRange(0, 23)]
  [int]$ActiveHoursStart = 8,
  [ValidateRange(0, 23)]
  [int]$ActiveHoursEnd = 22,
  [switch]$SkipPowerSettings,
  [switch]$SkipUpdatePolicies,
  [switch]$ConfigureAutoLogon,
  [string]$AutoLogonUser = "",
  [string]$AutoLogonDomain = "",
  [string]$AutoLogonPassword = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($ActiveHoursStart -eq $ActiveHoursEnd) {
  throw "ActiveHoursStart and ActiveHoursEnd cannot be the same value."
}

function Write-Step {
  param([string]$Message)
  Write-Host "[setup] $Message" -ForegroundColor Cyan
}

function Ensure-Administrator {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell session (Run as Administrator)."
  }
}

function Ensure-Directory {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -Path $Path -ItemType Directory -Force | Out-Null
  }
}

function Set-RegistryString {
  param(
    [string]$Path,
    [string]$Name,
    [string]$Value
  )
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -Path $Path -Force | Out-Null
  }
  New-ItemProperty -Path $Path -Name $Name -PropertyType String -Value $Value -Force | Out-Null
}

function Set-RegistryDword {
  param(
    [string]$Path,
    [string]$Name,
    [int]$Value
  )
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -Path $Path -Force | Out-Null
  }
  New-ItemProperty -Path $Path -Name $Name -PropertyType DWord -Value $Value -Force | Out-Null
}

function Invoke-PowerCfg {
  param([string[]]$Arguments)
  $null = & powercfg.exe @Arguments 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw "powercfg failed for arguments: $($Arguments -join ' ')"
  }
}

function Write-AsciiFile {
  param(
    [string]$Path,
    [string]$Content
  )
  Set-Content -Path $Path -Value $Content -Encoding Ascii -Force
}

function ConvertTo-PlainText {
  param([Security.SecureString]$SecureValue)
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
  }
  finally {
    if ($ptr -ne [IntPtr]::Zero) {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
  }
}

function Build-PrincipalUser {
  param(
    [string]$Domain,
    [string]$User
  )
  $normalizedDomain = ($Domain | ForEach-Object { $_.Trim() })
  $normalizedUser = ($User | ForEach-Object { $_.Trim() })
  if ([string]::IsNullOrWhiteSpace($normalizedUser)) {
    throw "AutomationUser is required."
  }
  if ([string]::IsNullOrWhiteSpace($normalizedDomain)) {
    return $normalizedUser
  }
  return "$normalizedDomain\$normalizedUser"
}

Ensure-Administrator

$automationRootFull = [System.IO.Path]::GetFullPath($AutomationRoot)
$logsPath = Join-Path $automationRootFull "logs"
$managedScriptsPath = Join-Path $automationRootFull "managed-scripts.json"
$startOutlookPath = Join-Path $automationRootFull "start-outlook.ps1"
$startAllPath = Join-Path $automationRootFull "start-all.ps1"
$watchdogPath = Join-Path $automationRootFull "watchdog.ps1"
$exampleAgentPath = Join-Path $automationRootFull "example-agent.ps1"
$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$principalUser = Build-PrincipalUser -Domain $AutomationDomain -User $AutomationUser

Write-Step "Creating automation directory structure."
Ensure-Directory -Path $automationRootFull
Ensure-Directory -Path $logsPath

if (-not $SkipPowerSettings) {
  Write-Step "Applying power settings (disable sleep and hibernate)."
  Invoke-PowerCfg -Arguments @("/change", "standby-timeout-ac", "0")
  Invoke-PowerCfg -Arguments @("/change", "standby-timeout-dc", "0")
  Invoke-PowerCfg -Arguments @("/change", "hibernate-timeout-ac", "0")
  Invoke-PowerCfg -Arguments @("/change", "hibernate-timeout-dc", "0")
  Invoke-PowerCfg -Arguments @("/hibernate", "off")
}
else {
  Write-Step "Skipping power settings because -SkipPowerSettings was provided."
}

if (-not $SkipUpdatePolicies) {
  Write-Step "Applying update and restart policies to reduce unexpected restarts."
  $wuPolicyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
  Set-RegistryDword -Path $wuPolicyPath -Name "NoAutoRebootWithLoggedOnUsers" -Value 1
  Set-RegistryDword -Path $wuPolicyPath -Name "AUOptions" -Value 3

  $wuUxPath = "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
  Set-RegistryDword -Path $wuUxPath -Name "ActiveHoursStart" -Value $ActiveHoursStart
  Set-RegistryDword -Path $wuUxPath -Name "ActiveHoursEnd" -Value $ActiveHoursEnd
  Set-RegistryDword -Path $wuUxPath -Name "SmartActiveHoursState" -Value 0
}
else {
  Write-Step "Skipping update policies because -SkipUpdatePolicies was provided."
}

if ($ConfigureAutoLogon) {
  Write-Step "Configuring Windows auto-logon."

  $resolvedAutoUser = if ([string]::IsNullOrWhiteSpace($AutoLogonUser)) { $AutomationUser } else { $AutoLogonUser }
  $resolvedAutoDomain = if ([string]::IsNullOrWhiteSpace($AutoLogonDomain)) { $AutomationDomain } else { $AutoLogonDomain }
  $resolvedAutoPassword = $AutoLogonPassword

  if ([string]::IsNullOrWhiteSpace($resolvedAutoPassword)) {
    $securePassword = Read-Host -Prompt "Enter auto-logon password for $resolvedAutoDomain\$resolvedAutoUser" -AsSecureString
    $resolvedAutoPassword = ConvertTo-PlainText -SecureValue $securePassword
  }

  if ([string]::IsNullOrWhiteSpace($resolvedAutoPassword)) {
    throw "Auto-logon password cannot be empty when -ConfigureAutoLogon is used."
  }

  $winlogonPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
  Set-RegistryString -Path $winlogonPath -Name "AutoAdminLogon" -Value "1"
  Set-RegistryString -Path $winlogonPath -Name "DefaultUserName" -Value $resolvedAutoUser
  Set-RegistryString -Path $winlogonPath -Name "DefaultDomainName" -Value $resolvedAutoDomain
  Set-RegistryString -Path $winlogonPath -Name "DefaultPassword" -Value $resolvedAutoPassword
  Set-RegistryString -Path $winlogonPath -Name "ForceAutoLogon" -Value "1"
}
else {
  Write-Step "Auto-logon was not changed. Use -ConfigureAutoLogon to configure it."
}

Write-Step "Writing runtime scripts under $automationRootFull."

$startOutlookScript = @'
[CmdletBinding()]
param(
  [string]$LogPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($LogPath)) {
  $LogPath = Join-Path $PSScriptRoot "logs\start-outlook.log"
}

if (-not (Test-Path -LiteralPath (Split-Path -Parent $LogPath))) {
  New-Item -Path (Split-Path -Parent $LogPath) -ItemType Directory -Force | Out-Null
}

function Write-Log {
  param([string]$Message)
  $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $LogPath -Value "$timestamp $Message"
}

if (Get-Process -Name "OUTLOOK" -ErrorAction SilentlyContinue) {
  Write-Log "Outlook already running."
  return
}

$candidates = @(
  "$env:ProgramFiles\Microsoft Office\root\Office16\OUTLOOK.EXE",
  "$env:ProgramFiles(x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
  "$env:ProgramFiles\Microsoft Office\Office16\OUTLOOK.EXE",
  "$env:ProgramFiles(x86)\Microsoft Office\Office16\OUTLOOK.EXE"
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

$outlookPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $outlookPath) {
  throw "Could not find OUTLOOK.EXE in default install locations."
}

Start-Process -FilePath $outlookPath -WindowStyle Minimized
Write-Log "Started Outlook from $outlookPath."
'@

$startAllScript = @'
[CmdletBinding()]
param(
  [string]$ConfigPath = "",
  [string]$LogPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
  $ConfigPath = Join-Path $PSScriptRoot "managed-scripts.json"
}
if ([string]::IsNullOrWhiteSpace($LogPath)) {
  $LogPath = Join-Path $PSScriptRoot "logs\start-all.log"
}

if (-not (Test-Path -LiteralPath (Split-Path -Parent $LogPath))) {
  New-Item -Path (Split-Path -Parent $LogPath) -ItemType Directory -Force | Out-Null
}

function Write-Log {
  param([string]$Message)
  $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $LogPath -Value "$timestamp $Message"
}

function Test-MatchPatternRunning {
  param([string]$MatchPattern)
  if ([string]::IsNullOrWhiteSpace($MatchPattern)) {
    return $false
  }

  $escapedPattern = [Regex]::Escape($MatchPattern)
  $matches = Get-CimInstance Win32_Process | Where-Object {
    $commandLine = [string]$_.CommandLine
    $commandLine -match $escapedPattern
  }
  return ($matches.Count -gt 0)
}

& (Join-Path $PSScriptRoot "start-outlook.ps1") -LogPath (Join-Path $PSScriptRoot "logs\start-outlook.log")

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  Write-Log "managed-scripts.json not found at $ConfigPath. No custom scripts started."
  return
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$scriptEntries = @($config.scripts)
if ($scriptEntries.Count -eq 0) {
  Write-Log "No managed scripts are configured."
  return
}

foreach ($entry in $scriptEntries) {
  $enabled = $true
  if ($entry.PSObject.Properties.Match("enabled").Count -gt 0) {
    $enabled = [bool]$entry.enabled
  }
  if (-not $enabled) {
    Write-Log "Skipping disabled entry: $($entry.name)."
    continue
  }

  $name = [string]$entry.name
  $command = [string]$entry.command
  $arguments = [string]$entry.arguments
  $workingDirectory = [string]$entry.workingDirectory
  $matchPattern = [string]$entry.matchPattern

  if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($command)) {
    Write-Log "Skipping invalid entry (name/command required)."
    continue
  }

  if (Test-MatchPatternRunning -MatchPattern $matchPattern) {
    Write-Log "Already running: $name ($matchPattern)."
    continue
  }

  try {
    $startParams = @{
      FilePath = $command
      ArgumentList = $arguments
      WindowStyle = "Hidden"
    }
    if (-not [string]::IsNullOrWhiteSpace($workingDirectory)) {
      $startParams.WorkingDirectory = $workingDirectory
    }

    Start-Process @startParams | Out-Null
    Write-Log "Started: $name."
  }
  catch {
    Write-Log "Failed to start $name. Error: $($_.Exception.Message)"
  }
}
'@

$watchdogScript = @'
[CmdletBinding()]
param(
  [string]$ConfigPath = "",
  [string]$LogPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
  $ConfigPath = Join-Path $PSScriptRoot "managed-scripts.json"
}
if ([string]::IsNullOrWhiteSpace($LogPath)) {
  $LogPath = Join-Path $PSScriptRoot "logs\watchdog.log"
}

if (-not (Test-Path -LiteralPath (Split-Path -Parent $LogPath))) {
  New-Item -Path (Split-Path -Parent $LogPath) -ItemType Directory -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogPath -Value "$timestamp watchdog run started"
& (Join-Path $PSScriptRoot "start-all.ps1") -ConfigPath $ConfigPath -LogPath (Join-Path $PSScriptRoot "logs\start-all.log")
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogPath -Value "$timestamp watchdog run completed"
'@

$exampleAgentScript = @'
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$logPath = Join-Path $PSScriptRoot "logs\example-agent.log"
if (-not (Test-Path -LiteralPath (Split-Path -Parent $logPath))) {
  New-Item -Path (Split-Path -Parent $logPath) -ItemType Directory -Force | Out-Null
}

while ($true) {
  $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $logPath -Value "$timestamp example agent heartbeat"
  Start-Sleep -Seconds 60
}
'@

Write-AsciiFile -Path $startOutlookPath -Content $startOutlookScript
Write-AsciiFile -Path $startAllPath -Content $startAllScript
Write-AsciiFile -Path $watchdogPath -Content $watchdogScript

if (-not (Test-Path -LiteralPath $exampleAgentPath)) {
  Write-AsciiFile -Path $exampleAgentPath -Content $exampleAgentScript
}

if (-not (Test-Path -LiteralPath $managedScriptsPath)) {
  Write-Step "Creating managed-scripts.json template."
  $defaultConfig = @{
    scripts = @(
      @{
        name = "ExampleAgentDisabled"
        command = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
        arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$exampleAgentPath`""
        workingDirectory = $automationRootFull
        matchPattern = "example-agent.ps1"
        enabled = $false
      }
    )
  }
  $defaultConfig | ConvertTo-Json -Depth 6 | Set-Content -Path $managedScriptsPath -Encoding Ascii
}
else {
  Write-Step "managed-scripts.json already exists; leaving it unchanged."
}

Write-Step "Registering scheduled tasks."

$taskSettings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId $principalUser -LogonType InteractiveToken -RunLevel Highest

$startOutlookTrigger = New-ScheduledTaskTrigger -AtLogOn -User $principalUser
if ($startOutlookTrigger.PSObject.Properties.Match("Delay").Count -gt 0) {
  $startOutlookTrigger.Delay = "PT${OutlookDelaySeconds}S"
}
$startOutlookAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startOutlookPath`""
Register-ScheduledTask -TaskName "$TaskPrefix-StartOutlook" -Action $startOutlookAction -Trigger $startOutlookTrigger -Settings $taskSettings -Principal $principal -Force | Out-Null

$startAllTrigger = New-ScheduledTaskTrigger -AtLogOn -User $principalUser
if ($startAllTrigger.PSObject.Properties.Match("Delay").Count -gt 0) {
  $startAllTrigger.Delay = "PT${ScriptsDelaySeconds}S"
}
$startAllAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startAllPath`" -ConfigPath `"$managedScriptsPath`""
Register-ScheduledTask -TaskName "$TaskPrefix-StartAllScripts" -Action $startAllAction -Trigger $startAllTrigger -Settings $taskSettings -Principal $principal -Force | Out-Null

$watchdogLogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $principalUser
if ($watchdogLogonTrigger.PSObject.Properties.Match("Delay").Count -gt 0) {
  $watchdogLogonTrigger.Delay = "PT${WatchdogLogonDelaySeconds}S"
}
$watchdogRepeatTrigger = New-ScheduledTaskTrigger -Daily -At 12:00AM
if ($watchdogRepeatTrigger.PSObject.Properties.Match("Repetition").Count -gt 0) {
  $watchdogRepeatTrigger.Repetition.Interval = "PT${WatchdogIntervalMinutes}M"
  $watchdogRepeatTrigger.Repetition.Duration = "P1D"
}
$watchdogAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$watchdogPath`" -ConfigPath `"$managedScriptsPath`""
Register-ScheduledTask -TaskName "$TaskPrefix-Watchdog" -Action $watchdogAction -Trigger @($watchdogLogonTrigger, $watchdogRepeatTrigger) -Settings $taskSettings -Principal $principal -Force | Out-Null

Write-Step "Setup complete."
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "1) Edit $managedScriptsPath and add your real scripts."
Write-Host "2) Reboot once and confirm auto-logon (if configured), Outlook start, and script launch."
Write-Host "3) Check logs in $logsPath."
Write-Host "4) Verify tasks in Task Scheduler: $TaskPrefix-StartOutlook, $TaskPrefix-StartAllScripts, $TaskPrefix-Watchdog."
Write-Host ""
if ($ConfigureAutoLogon) {
  Write-Warning "Auto-logon stores a password in the registry in plaintext. Use this only in a trusted VM."
}
