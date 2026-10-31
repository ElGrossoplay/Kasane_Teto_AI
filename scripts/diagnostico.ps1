# Kasane Teto AI Lite - Diagnostico de solo lectura
# No instala, no descarga, no modifica nada. Solo consulta y muestra informacion.
# Uso:  powershell -ExecutionPolicy Bypass -File .\scripts\diagnostico.ps1

$ErrorActionPreference = "SilentlyContinue"

function Titulo($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }

Titulo "Sistema operativo"
$os = Get-CimInstance Win32_OperatingSystem
"{0} | version {1} | build {2} | {3}" -f $os.Caption, $os.Version, $os.BuildNumber, $os.OSArchitecture

Titulo "CPU"
Get-CimInstance Win32_Processor | ForEach-Object {
    "{0} | nucleos: {1} | hilos: {2} | MHz max: {3}" -f $_.Name.Trim(), $_.NumberOfCores, $_.NumberOfLogicalProcessors, $_.MaxClockSpeed
}

Titulo "Memoria RAM"
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$libreGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
"Total: $totalGB GB | Libre ahora: $libreGB GB | En uso: $([math]::Round($totalGB - $libreGB, 2)) GB"

Titulo "GPUs (segun Windows; AdapterRAM no es fiable por encima de 4 GB)"
Get-CimInstance Win32_VideoController | ForEach-Object {
    "{0} | driver {1}" -f $_.Name, $_.DriverVersion
}

Titulo "NVIDIA (nvidia-smi, VRAM dedicada real)"
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
    nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw --format=csv
    Write-Host ""
    Write-Host "Version maxima de CUDA soportada por el driver:"
    (nvidia-smi | Select-String "CUDA.*Version") -replace '\s+', ' '
} else {
    "nvidia-smi no encontrado (driver NVIDIA ausente o fuera del PATH)."
}

Titulo "Python"
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { Write-Host "Lanzador 'py' - versiones instaladas:"; py -0p } else { "Lanzador 'py' no encontrado." }
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) { "python en PATH: $($python.Source)"; python --version } else { "'python' no esta en el PATH." }

Titulo "Git"
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) { git --version } else { "Git no encontrado." }

Titulo "Disco"
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    "{0} libre {1} GB de {2} GB" -f $_.DeviceID, [math]::Round($_.FreeSpace / 1GB, 1), [math]::Round($_.Size / 1GB, 1)
}

Titulo "Plan de energia activo"
powercfg /getactivescheme

Titulo "10 procesos que mas RAM usan"
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 |
    ForEach-Object { "{0,-30} {1,8} MB" -f $_.ProcessName, [math]::Round($_.WorkingSet64 / 1MB) }

Write-Host ""
Write-Host "Diagnostico terminado. Copia todo el texto y pegalo en el chat." -ForegroundColor Green
