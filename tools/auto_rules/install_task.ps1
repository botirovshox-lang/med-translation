# Ставит автоматический разбор случаев (раздел Ы7) в Планировщик Windows: раз в час.
#   powershell -NoProfile -File tools\auto_rules\install_task.ps1          # поставить
#   powershell -NoProfile -File tools\auto_rules\install_task.ps1 -Remove  # снять
# Раннер берётся из origin/main (git show), а не из рабочего каталога: файл
# на диске мог бы поправить кто угодно, включая самого агента. Задача зовёт
# короткий загрузчик (у schtasks команда не длиннее 261 знака).
param([switch]$Remove, [string]$Repo = "C:\Users\Shox\med_translation")
$name = "medcat-auto-rules"
if ($Remove) {
    schtasks /Delete /TN $name /F | Out-Null
    Write-Output "снято: $name"
    exit 0
}
$bash = "C:\Program Files\Git\bin\bash.exe"
if (-not (Test-Path $bash)) { Write-Error "нет Git Bash: $bash"; exit 1 }
$state = Join-Path $env:USERPROFILE ".medcat-auto-rules"
New-Item -ItemType Directory -Force $state | Out-Null
$r = $Repo -replace '\\', '/'
$boot = @"
#!/usr/bin/env bash
cd '$r' || exit 1
git fetch -q origin || exit 1
git show origin/main:tools/auto_rules/run.sh > "`$HOME/.medcat-auto-rules/run-origin.sh" || exit 1
exec bash "`$HOME/.medcat-auto-rules/run-origin.sh"
"@
[IO.File]::WriteAllText((Join-Path $state "boot.sh"), $boot.Replace("`r`n", "`n"))
$cmd = "`"$bash`" -l `"$($state -replace '\\','/')/boot.sh`""
schtasks /Create /TN $name /SC HOURLY /MO 1 /TR $cmd /F | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "schtasks не поставил задачу"; exit 1 }
Write-Output "поставлено: $name, раз в час; выключить — файл $state\OFF"
