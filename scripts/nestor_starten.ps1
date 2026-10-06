# Nestor starten: Coach im Hintergrund, Dashboard als eigenes Fenster im Vollbild (F11 verlässt das Vollbild).
# Fenster zu = Coach aus. Läuft noch ein Meeting, wird vorher gefragt.
# Aufruf über "Nestor starten.cmd" im Repo-Ordner.

$ErrorActionPreference = "Stop"
$wurzel = Split-Path -Parent $PSScriptRoot
$port = if ($env:LMC_PORT) { [int]$env:LMC_PORT } else { 8000 }
$adresse = "http://127.0.0.1:$port"
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
          "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
# eigenes Edge-Profil: so gehört das Fenster zu einem eigenen Prozess, auf dessen Ende wir warten können;
# die Mikrofon-Freigabe merkt sich das Profil
$profil = Join-Path $env:LOCALAPPDATA "live-meeting-coach\edge-profil"
Add-Type -AssemblyName System.Windows.Forms

function Laeuft {
    try { Invoke-RestMethod "$adresse/api/zustand" -TimeoutSec 2 } catch { $null }
}

if (-not $edge) {
    [System.Windows.Forms.MessageBox]::Show("Microsoft Edge wurde nicht gefunden.", "Nestor") | Out-Null
    exit 1
}

# 1. Coach starten, falls er nicht schon läuft (dann gehört er nicht uns und bleibt nach dem Fenster an)
$eigener = $null
if (-not (Laeuft)) {
    $logs = Join-Path $wurzel "logs"
    New-Item -ItemType Directory -Force $logs | Out-Null
    $eigener = Start-Process -FilePath (Join-Path $wurzel ".venv\Scripts\python.exe") -ArgumentList "-m", "coach" `
        -WorkingDirectory $wurzel -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "server.out.log") -RedirectStandardError (Join-Path $logs "server.err.log")
    $bis = (Get-Date).AddSeconds(30)
    while (-not (Laeuft)) {
        if ($eigener.HasExited -or (Get-Date) -gt $bis) {
            [System.Windows.Forms.MessageBox]::Show("Der Coach ist nicht gestartet. Details: logs\server.err.log", "Nestor") | Out-Null
            exit 1
        }
        Start-Sleep -Milliseconds 300
    }
}

# 2. Dashboard als App-Fenster im Vollbild; warten, bis es geschlossen wird
while ($true) {
    Start-Process -FilePath $edge -Wait -ArgumentList "--app=$adresse", "--start-fullscreen", "--user-data-dir=`"$profil`"",
        "--no-first-run", "--no-default-browser-check"
    if (-not $eigener) { break }  # fremder Coach (z. B. aus einer Entwicklersitzung): nicht anfassen
    $z = Laeuft
    if ($z -and $z.hoeren) {
        $antwort = [System.Windows.Forms.MessageBox]::Show(
            "Das Meeting läuft noch. Beenden und Nestor ausschalten?`n`nNein öffnet das Fenster wieder.",
            "Nestor", "YesNo", "Question")
        if ($antwort -ne "Yes") { continue }
        try { Invoke-RestMethod "$adresse/api/stopp" -Method Post -TimeoutSec 30 | Out-Null } catch { }
    }
    break
}

# 3. Coach aus
# python.exe aus der venv ist unter Windows nur ein Starter mit dem echten Python als Kindprozess – ganzen Baum beenden
if ($eigener -and -not $eigener.HasExited) { taskkill /PID $eigener.Id /T /F | Out-Null }
