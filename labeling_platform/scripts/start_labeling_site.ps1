param(
    [switch]$Loop,
    [int]$IntervalSeconds = 300
)

$ErrorActionPreference = 'Continue'

$Root = 'C:\SAIL_David\Project\GCM\labeling_interface'
$DataDir = Join-Path $Root 'data'
$LogDir = Join-Path $Root 'logs'
$StreamlitExe = 'C:\Users\huang\anaconda3\Scripts\streamlit.exe'
$NgrokExe = 'C:\tools\ngrok\ngrok.exe'
$NgrokConfig = 'C:\tools\ngrok\ngrok.yml'
$Port = 8501
$NgrokUrl = 'https://default.internal'
$PublicHealthUrl = 'https://usc.sail.gcm.coding.labeling.ngrok.io/_stcore/health'
$LocalHealthUrl = "http://127.0.0.1:$Port/_stcore/health"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$RunLog = Join-Path $LogDir 'labeling_autostart.log'

function Write-RunLog {
    param([string]$Message)
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $RunLog -Value "[$ts] $Message"
}

function Test-StreamlitHealth {
    param(
        [string]$Uri,
        [int]$TimeoutSec = 8
    )
    try {
        $response = Invoke-WebRequest -Uri $Uri -Headers @{ 'ngrok-skip-browser-warning' = 'true' } -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'ok')
    } catch {
        return $false
    }
}

function Wait-StreamlitHealth {
    param(
        [string]$Uri,
        [int]$Seconds = 45
    )
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-StreamlitHealth -Uri $Uri -TimeoutSec 5) {
            return $true
        }
        Start-Sleep -Seconds 3
    }
    return $false
}

function Get-LabelingStreamlitProcess {
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -in @('streamlit.exe', 'python.exe')) -and
        (
            $_.CommandLine -match 'labeling_platform\\app\.py' -or
            ($_.CommandLine -match 'streamlit-script\.py' -and $_.CommandLine -match 'labeling_platform')
        )
    }
}

function Get-LabelingNgrokProcess {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'ngrok.exe' -and
        $_.CommandLine -match 'http 8501' -and
        $_.CommandLine -match [regex]::Escape($NgrokUrl)
    }
}

function Stop-Processes {
    param($Processes)
    foreach ($proc in $Processes) {
        try {
            Stop-Process -Id $proc.ProcessId -Force
            Write-RunLog "Stopped stale process $($proc.Name) pid=$($proc.ProcessId)."
        } catch {
            Write-RunLog "Could not stop process pid=$($proc.ProcessId): $($_.Exception.Message)"
        }
    }
}

function Start-LabelingStreamlit {
    if (-not (Test-Path $StreamlitExe)) {
        Write-RunLog "Missing Streamlit executable: $StreamlitExe"
        return
    }
    $ts = Get-Date -Format 'yyyyMMddTHHmmss'
    $stdout = Join-Path $LogDir "autostart_streamlit_out_$ts.log"
    $stderr = Join-Path $LogDir "autostart_streamlit_err_$ts.log"
    $args = @(
        'run',
        'labeling_platform\app.py',
        '--server.port',
        "$Port",
        '--server.address',
        '127.0.0.1',
        '--server.enableCORS',
        'false',
        '--server.enableXsrfProtection',
        'false',
        '--server.headless',
        'true'
    )
    $proc = Start-Process -FilePath $StreamlitExe -ArgumentList $args -WorkingDirectory $DataDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    Write-RunLog "Started Streamlit pid=$($proc.Id). stdout=$stdout stderr=$stderr"
}

function Start-LabelingNgrok {
    if (-not (Test-Path $NgrokExe)) {
        Write-RunLog "Missing ngrok executable: $NgrokExe"
        return
    }
    if (-not (Test-Path $NgrokConfig)) {
        Write-RunLog "Missing ngrok config: $NgrokConfig"
        return
    }
    $ts = Get-Date -Format 'yyyyMMddTHHmmss'
    $stdout = Join-Path $LogDir "autostart_ngrok_out_$ts.log"
    $stderr = Join-Path $LogDir "autostart_ngrok_err_$ts.log"
    $args = @(
        'http',
        "$Port",
        '--url',
        $NgrokUrl,
        '--config',
        $NgrokConfig,
        '--inspect=false',
        '--log',
        'stdout'
    )
    $proc = Start-Process -FilePath $NgrokExe -ArgumentList $args -WorkingDirectory $DataDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    Write-RunLog "Started ngrok pid=$($proc.Id). stdout=$stdout stderr=$stderr"
}

function Invoke-LabelingCheck {

Write-RunLog 'Autostart check begin.'

$localHealthy = Test-StreamlitHealth -Uri $LocalHealthUrl
if (-not $localHealthy) {
    $existingStreamlit = @(Get-LabelingStreamlitProcess)
    if ($existingStreamlit.Count -gt 0) {
        Write-RunLog "Local health is down; restarting $($existingStreamlit.Count) labeling Streamlit process(es)."
        Stop-Processes -Processes $existingStreamlit
        Start-Sleep -Seconds 3
    } else {
        Write-RunLog 'Local health is down and no labeling Streamlit process was found.'
    }
    Start-LabelingStreamlit
    $localHealthy = Wait-StreamlitHealth -Uri $LocalHealthUrl -Seconds 60
}
Write-RunLog "Local health: $localHealthy"

$publicHealthy = Test-StreamlitHealth -Uri $PublicHealthUrl -TimeoutSec 12
if (-not $publicHealthy) {
    $existingNgrok = @(Get-LabelingNgrokProcess)
    if ($existingNgrok.Count -gt 0) {
        Write-RunLog "Public health is down; restarting $($existingNgrok.Count) labeling ngrok process(es)."
        Stop-Processes -Processes $existingNgrok
        Start-Sleep -Seconds 3
    } else {
        Write-RunLog 'Public health is down and no labeling ngrok process was found.'
    }
    Start-LabelingNgrok
    $publicHealthy = Wait-StreamlitHealth -Uri $PublicHealthUrl -Seconds 75
}
Write-RunLog "Public health: $publicHealthy"
Write-RunLog 'Autostart check end.'

}

if ($Loop) {
    # Single persistent hidden process that self-checks on an interval.
    # Replaces the old "relaunch powershell every 5 minutes" scheduled task,
    # which flashed a console window on each spawn.
    $createdNew = $false
    $mutex = New-Object System.Threading.Mutex($true, "GCM_Labeling_KeepAlive_Loop", [ref]$createdNew)
    if (-not $createdNew) {
        Write-RunLog 'Another keep-alive loop is already running in this session; exiting duplicate.'
        return
    }
    try {
        Write-RunLog "Keep-alive loop started (interval ${IntervalSeconds}s, PID $PID)."
        while ($true) {
            Invoke-LabelingCheck
            Start-Sleep -Seconds $IntervalSeconds
        }
    } finally {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }
} else {
    Invoke-LabelingCheck
}
