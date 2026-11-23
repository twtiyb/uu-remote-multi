#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
Default: inspect only. -Apply: back up and rebuild the UU identity of this Windows VM.
Run inside the affected guest, with UU open and signed out. Supports 4.48.1.5606.
The script never changes Windows MachineGuid, SID, SMBIOS, disks, MACs or account passwords.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$NoLaunch,
    [string]$InstallRoot = "$env:ProgramFiles\Netease\GameViewer"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$cli = Join-Path $InstallRoot 'bin\uuyc-cli.exe'
$launcher = Join-Path $InstallRoot 'GameViewer.exe'
$data = Join-Path $env:ProgramData 'Netease\GameViewer'
if (-not (Test-Path -LiteralPath $cli)) { throw 'UU CLI not found at the selected installation.' }

# Query the live application rather than treating cached account data as a login.
$statusText = & $cli status --json 2>$null | Out-String
if ($LASTEXITCODE -ne 0) { throw 'Open UU before running this tool. Live login status is required.' }
$status = $statusText | ConvertFrom-Json
if (-not $status.success) { throw 'UU live status query failed.' }
if ($status.data.appVersion -ne '4.48.1.5606') { throw 'Untested UU version; refusing identity changes.' }
if ($status.data.isLoggedIn -ne $false) { throw 'Sign out of UU in this test/affected guest first, then run again.' }

$prefix = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\') + '\'
$mains = @(Get-CimInstance Win32_Process -Filter "Name='GameViewer.exe'" | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
})
if ($mains.Count -ne 1) { throw 'Exactly one UU main process is required.' }
$owner = Invoke-CimMethod -InputObject $mains[0] -MethodName GetOwnerSid
if ($owner.ReturnValue -ne 0) { throw 'Cannot identify the UU desktop user.' }
$profileKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\' + $owner.Sid
$profile = [Environment]::ExpandEnvironmentVariables((Get-ItemProperty -LiteralPath $profileKey).ProfileImagePath)
if (-not (Test-Path -LiteralPath $profile)) { throw 'UU desktop user profile not found.' }
if (-not $NoLaunch -and [Diagnostics.Process]::GetCurrentProcess().SessionId -ne $mains[0].SessionId) {
    throw 'Run in the UU desktop session, or use -NoLaunch and reopen UU in that session yourself.'
}

$config = Join-Path $data 'config.ini'
$before = [IO.File]::ReadAllText($config)
if ([regex]::Matches($before, '(?m)^uuid=[^\r\n]+').Count -ne 1) { throw 'Unexpected config.ini UUID format.' }
$targets = [ordered]@{
    'config.ini' = $config
    'user_info.ini' = (Join-Path $data 'user_info.ini')
    'remote_assist_code.ini' = (Join-Path $data 'remote_assist_code.ini')
    'setting_guest_anonymous_id.ini' = (Join-Path $profile 'AppData\Local\GameViewer\setting_guest_anonymous_id.ini')
}
if (-not $Apply) {
    [ordered]@{
        inspectionOnly = $true
        appVersion = $status.data.appVersion
        signedOut = $true
        identityFilesPresent = @($targets.Keys | Where-Object { Test-Path -LiteralPath $targets[$_] })
        nextStep = 'Use -Apply to back up/reset this guest identity. Remote verification codes will be regenerated.'
    } | ConvertTo-Json -Depth 3
    return
}

# Backups include anonymous tokens and verification codes. Restrict their directory
# to SYSTEM and local administrators before copying any files into it.
$backupRoot = Join-Path $env:ProgramData 'UUIdentityBackups'
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$backup = Join-Path $backupRoot ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backup | Out-Null
$acl = Get-Acl -LiteralPath $backup
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
    $identity = New-Object System.Security.Principal.SecurityIdentifier($sid)
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $backup -AclObject $acl

$service = Get-Service -Name GameViewerService
$wasRunning = $service.Status -eq 'Running'
$written = $false
try {
    if ($wasRunning) { Stop-Service -Name GameViewerService -WarningAction SilentlyContinue }
    Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -and
        $_.Name -like 'GameViewer*'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop }
    if ([IO.File]::ReadAllText($config) -ne $before) { throw 'UU configuration changed during shutdown; retry inspection.' }
    $manifest = [ordered]@{ format = 'uu-windows-identity-v1'; files = @{}; version = $status.data.appVersion }
    foreach ($name in $targets.Keys) {
        $path = $targets[$name]
        if (Test-Path -LiteralPath $path) {
            Copy-Item -LiteralPath $path -Destination (Join-Path $backup $name)
            $manifest.files[$name] = $path
        }
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backup 'manifest.json') -Encoding UTF8
    # Each affected file has a complete backup before the first write.
    $newConfig = [regex]::Replace($before, '(?m)^uuid=[^\r\n]+', ('uuid=' + [Guid]::NewGuid().ToString()))
    [IO.File]::WriteAllText($config, $newConfig, (New-Object System.Text.UTF8Encoding($false)))
    foreach ($name in @('user_info.ini', 'remote_assist_code.ini', 'setting_guest_anonymous_id.ini')) {
        $path = $targets[$name]
        if (Test-Path -LiteralPath $path) { Move-Item -LiteralPath $path -Destination (Join-Path $backup ($name + '.moved')) }
    }
    $written = $true
} catch {
    # Restore originals on a partial reset before restarting any UU process.
    foreach ($name in $targets.Keys) {
        $saved = Join-Path $backup $name
        if (Test-Path -LiteralPath $saved) { Copy-Item -LiteralPath $saved -Destination $targets[$name] -Force }
    }
    throw
} finally {
    if ($wasRunning) { Start-Service -Name GameViewerService }
}
if ($written -and -not $NoLaunch) { Start-Process -FilePath $launcher -WorkingDirectory $InstallRoot }
[ordered]@{
    identityReset = $written
    backup = $backup
    reopenUU = [bool]$NoLaunch
    nextStep = 'Wait for a new assist ID, configure verification codes in UU, then verify simultaneous connections and restart persistence.'
} | ConvertTo-Json
