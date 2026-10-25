# Ставит автоматический разбор случаев (раздел Ы7) в Планировщик Windows: раз в час.
#   powershell -NoProfile -File tools\auto_rules\install_task.ps1          # поставить
#   powershell -NoProfile -File tools\auto_rules\install_task.ps1 -Remove  # снять
param([switch]$Remove, [string]$Repo = "C:\Users\Shox\med_translation")
$name = "medcat-auto-rules"
if ($Remove) {
    schtasks /Delete /TN $name /F | Out-Null
    Write-Output "снято: $name"
    exit 0
}
$bash = "C:\Program Files\Git\bin\bash.exe"
if (-not (Test-Path $bash)) { Write-Error "нет Git Bash: $bash"; exit 1 }
$cmd = "`"$bash`" -lc `"cd '$($Repo -replace '\\','/')' && bash tools/auto_rules/run.sh`""
schtasks /Create /TN $name /SC HOURLY /MO 1 /TR $cmd /F | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "schtasks не поставил задачу"; exit 1 }
Write-Output "поставлено: $name, раз в час; выключить — файл $env:USERPROFILE\.medcat-auto-rules\OFF"
