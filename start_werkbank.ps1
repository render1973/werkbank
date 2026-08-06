<#
.SYNOPSIS
    Startet Hub und Sidecar der KI-Werkbank in zwei getrennten, sichtbaren
    Fenstern und prueft anschliessend aktiv, ob beide erreichbar sind.

.DESCRIPTION
    Rein manuell auszufuehren - richtet KEINEN Autostart bei Windows-
    Login/-Boot ein. Einfach per Doppelklick oder aus einem Terminal:

        .\start_werkbank.ps1

    Falls die Ausfuehrung durch die PowerShell-Execution-Policy blockiert
    wird:

        powershell -ExecutionPolicy Bypass -File start_werkbank.ps1

    Bereits laufende Prozesse (Port 5000/5001 belegt) werden erkannt und
    NICHT doppelt gestartet.
#>

$ErrorActionPreference = 'Stop'

$WerkbankRoot   = $PSScriptRoot
$HubDir         = Join-Path $WerkbankRoot 'hub'
$SidecarDir     = Join-Path $WerkbankRoot 'apps\anonymisierung'
$OcrEnvActivate = 'C:\Users\thoma\ocr-env\Scripts\Activate.ps1'

function Test-PortListening {
    param([int]$Port)
    try {
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-InNewWindow {
    param([string]$Title, [string]$Command)
    $full = "`$host.UI.RawUI.WindowTitle = '$Title'; $Command"
    Start-Process powershell.exe -ArgumentList @(
        '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $full
    ) | Out-Null
}

function Wait-ForHealthy {
    # Pollt statt fest zu warten: der Sidecar importiert PaddleOCR/Presidio/
    # Torch bereits auf Modulebene (nicht lazy wie faster-whisper im Hub) -
    # das kann beim ersten Start je nach Maschine 10-30s+ dauern, bevor
    # Flask ueberhaupt zu horchen beginnt. Eine feste kurze Wartezeit haette
    # das faelschlich als "nicht erreichbar" gemeldet.
    param([string]$Name, [string]$Url, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
            if ($resp.StatusCode -eq 200) {
                Write-Host "$Name`: laeuft ($Url)" -ForegroundColor Green
                return $true
            }
        } catch {
            # noch nicht bereit - weiter pollen bis zum Timeout
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    Write-Host "$Name`: NICHT erreichbar nach ${TimeoutSeconds}s - $Name-Fenster pruefen." -ForegroundColor Yellow
    return $false
}

Write-Host ('=' * 60)
Write-Host 'KI-Werkbank starten'
Write-Host ('=' * 60)

# --- Sidecar (PDF-Anonymisierung, Port 5001) --------------------------------
if (Test-PortListening -Port 5001) {
    Write-Host 'Sidecar (Port 5001): laeuft bereits - ueberspringe Start.'
} elseif (-not (Test-Path $OcrEnvActivate)) {
    Write-Host "FEHLER: ocr-env nicht gefunden unter $OcrEnvActivate" -ForegroundColor Red
    Write-Host '        Sidecar wird NICHT gestartet. venv-Pfad pruefen oder neu anlegen.'
    Write-Host '        Hub wird trotzdem gestartet - PDF-Anonymisierung ist bis dahin nicht nutzbar.'
} else {
    Write-Host 'Starte Sidecar (PDF-Anonymisierung) in neuem Fenster ...'
    $sidecarCmd = "& '$OcrEnvActivate'; Set-Location '$SidecarDir'; python anonymize_service.py"
    Start-InNewWindow -Title 'KI-Werkbank - Sidecar (Port 5001)' -Command $sidecarCmd
}

# --- Hub (Transkription + Weboberflaeche, Port 5000) ------------------------
if (Test-PortListening -Port 5000) {
    Write-Host 'Hub (Port 5000): laeuft bereits - ueberspringe Start.'
} else {
    Write-Host 'Starte Hub in neuem Fenster ...'
    $hubCmd = "Set-Location '$HubDir'; .\start.bat"
    Start-InNewWindow -Title 'KI-Werkbank - Hub (Port 5000)' -Command $hubCmd
}

# --- Health-Checks (aktives Polling statt fester Wartezeit) -----------------
Write-Host ''
Write-Host 'Pruefe Erreichbarkeit (Sidecar-Import kann beim ersten Start dauern) ...'
Write-Host ''
Write-Host ('=' * 60)
Write-Host 'Status'
Write-Host ('=' * 60)

Wait-ForHealthy -Name 'Sidecar' -Url 'http://127.0.0.1:5001/health' -TimeoutSeconds 45 | Out-Null
Wait-ForHealthy -Name 'Hub'     -Url 'http://127.0.0.1:5000/'       -TimeoutSeconds 20 | Out-Null

Write-Host ('=' * 60)
