# Run this script as Administrator (right-click -> Run with PowerShell as admin)
# Installs two Windows services that survive reboots and auto-restart on crash:
#   1) GCMLabelingStreamlit  -> runs the Streamlit labeling app on 127.0.0.1:8501
#   2) GCMLabelingNgrok      -> binds local 8501 to your ngrok cloud endpoint

$ErrorActionPreference = 'Stop'

# --- Config (edit only if paths change) ---
$NssmPath      = 'C:\Users\huang\AppData\Local\Microsoft\WinGet\Packages\NSSM.NSSM_Microsoft.Winget.Source_8wekyb3d8bbwe\nssm-2.24-101-g897c7ad\win32\nssm.exe'
$StreamlitExe  = 'C:\Users\huang\anaconda3\Scripts\streamlit.exe'
$NgrokExe      = 'C:\tools\ngrok\ngrok.exe'
$AppDir        = 'C:\SAIL_David\Project\GCM\labeling_interface\data'
$AppScript     = 'labeling_platform\app.py'
$LogDir        = 'C:\SAIL_David\Project\GCM\labeling_interface\logs'
# Public reserved domain (one Agent endpoint). Avoid extra Cloud+Internal endpoints to reduce billing.
$NgrokPublicUrl = 'https://usc.sail.gcm.coding.labeling.ngrok.io'
$Port           = 8501

# Sanity checks
foreach ($p in @($NssmPath, $StreamlitExe, $NgrokExe, $AppDir)) {
    if (-not (Test-Path $p)) { throw "Missing: $p" }
}
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# Stop any leftover background processes from prior interactive runs
Get-Process ngrok -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process streamlit -ErrorAction SilentlyContinue | Stop-Process -Force
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) { try { Stop-Process -Id $c.OwningProcess -Force } catch {} }

function Install-NssmService {
    param(
        [string]$Name,
        [string]$Exe,
        [string]$AppArgs,
        [string]$WorkDir,
        [string]$Stdout,
        [string]$Stderr
    )
    $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Removing existing service: $Name"
        & $NssmPath stop    $Name | Out-Null
        & $NssmPath remove  $Name confirm | Out-Null
    }
    Write-Host "Installing service: $Name"
    & $NssmPath install $Name $Exe | Out-Null
    & $NssmPath set $Name AppParameters       $AppArgs
    & $NssmPath set $Name AppDirectory         $WorkDir
    & $NssmPath set $Name AppStdout            $Stdout
    & $NssmPath set $Name AppStderr            $Stderr
    & $NssmPath set $Name AppStdoutCreationDisposition 4
    & $NssmPath set $Name AppStderrCreationDisposition 4
    & $NssmPath set $Name AppRotateFiles       1
    & $NssmPath set $Name AppRotateBytes       10485760
    & $NssmPath set $Name AppExit Default      Restart
    & $NssmPath set $Name AppRestartDelay      5000
    & $NssmPath set $Name Start                SERVICE_AUTO_START
    & $NssmPath set $Name Description          "GCM Labeling Platform background service"
}

$StreamlitArgs = "run `"$AppScript`" --server.port $Port --server.address 127.0.0.1 --server.enableCORS false --server.enableXsrfProtection false --server.headless true"
$NgrokConfig   = 'C:\tools\ngrok\ngrok.yml'
$NgrokArgs     = "http $Port --url $NgrokPublicUrl --config `"$NgrokConfig`" --log stdout"

Install-NssmService -Name 'GCMLabelingStreamlit' -Exe $StreamlitExe -AppArgs $StreamlitArgs -WorkDir $AppDir -Stdout (Join-Path $LogDir 'streamlit_out.log') -Stderr (Join-Path $LogDir 'streamlit_err.log')
Install-NssmService -Name 'GCMLabelingNgrok'     -Exe $NgrokExe     -AppArgs $NgrokArgs     -WorkDir $AppDir -Stdout (Join-Path $LogDir 'ngrok_out.log')     -Stderr (Join-Path $LogDir 'ngrok_err.log')

Start-Service GCMLabelingStreamlit
Start-Sleep -Seconds 4
Start-Service GCMLabelingNgrok
Start-Sleep -Seconds 4

Get-Service GCMLabelingStreamlit, GCMLabelingNgrok | Format-Table Name, Status, StartType

try {
    $local = Invoke-WebRequest -Uri ("http://127.0.0.1:" + $Port) -UseBasicParsing -TimeoutSec 10
    Write-Host ("local_status=" + $local.StatusCode)
} catch {
    Write-Host ("local_error=" + $_.Exception.Message)
}
try {
    $public = Invoke-WebRequest -Uri 'https://usc.sail.gcm.coding.labeling.ngrok.io' -UseBasicParsing -TimeoutSec 15
    $title = if ($public.Content -match '<title>([^<]+)</title>') { $matches[1] } else { 'no_title' }
    Write-Host ("public_status=" + $public.StatusCode + " title=" + $title)
} catch {
    Write-Host ("public_error=" + $_.Exception.Message)
}

Write-Host "Done. Logs at: $LogDir"
