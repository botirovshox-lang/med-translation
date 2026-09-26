#!/usr/bin/env bash
# Запуск разового скрипта на боевом сервере — с копией базы ДО запуска.
# Использование: bash tools/prod_run.sh путь/к/скрипту.py
# Копия: /root/backups/medcat-before-<stamp>.sql.gz, журнал: /root/backups/prod_run.log.
# Откат: восстановить копию в отдельную базу, сверить, затем заменить боевую
# при остановленных medcat и medcat-worker (всё сделанное после копии пропадёт).
set -euo pipefail
SCRIPT="${1:-}"
[ -f "$SCRIPT" ] || { echo "нет файла: $SCRIPT"; exit 1; }
case "$SCRIPT" in *.py) ;; *) echo "только .py-скрипты"; exit 1;; esac
STAMP=$(date +%Y%m%d-%H%M%S)
scp -q "$SCRIPT" "beget:/tmp/prod_run_$STAMP.py"
ssh beget "set -eo pipefail
  mkdir -p /root/backups
  sudo -u postgres pg_dump -p 5433 medcat | gzip > /root/backups/medcat-before-$STAMP.sql.gz
  echo 'копия базы: /root/backups/medcat-before-$STAMP.sql.gz'
  echo '=== $STAMP $(basename "$SCRIPT")' >> /root/backups/prod_run.log
  cd /opt/med-translation
  .venv/bin/python /tmp/prod_run_$STAMP.py 2>&1 | tee -a /root/backups/prod_run.log
  rm -f /tmp/prod_run_$STAMP.py"
