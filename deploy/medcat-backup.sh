#!/bin/sh
# Резервная копия базы. Источник правды — PostgreSQL (см. CLAUDE.md,
# инвариант 2), а почасовой JSON в data/backups — это снимок STATE, то есть
# страховка на случай беды с базой, но НЕ её замена: в JSON нет ни очереди
# прогонов, ни счётчика расхода, ни версий документов.
#
# Ставится в cron root'а:
#   0 3 * * * /usr/local/bin/medcat-backup.sh
set -eu
DIR=/opt/med-translation/backend/data/backups
KEEP=14
mkdir -p "$DIR"
OUT="$DIR/db-$(date +%Y%m%d-%H%M).sql.gz"
sudo -u postgres pg_dump -p 5433 medcat | gzip > "$OUT"
# Пустой дамп — это не бэкап: лучше упасть громко, чем копить нули.
test -s "$OUT" || { echo "medcat-backup: пустой дамп $OUT" >&2; rm -f "$OUT"; exit 1; }
ls -t "$DIR"/db-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
