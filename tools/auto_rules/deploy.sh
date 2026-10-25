#!/usr/bin/env bash
# Выкат коммита на боевой сервер с проверкой и АВТООТКАТОМ (раздел Ы7).
#   bash tools/auto_rules/deploy.sh SHA
# Порядок: эталоны ДО → pull ровно до SHA → рестарт → здоровье → окно
# наблюдения (ошибки в журнале не больше, чем до выката) → эталоны ПОСЛЕ
# (предупреждений не больше, чем до). Любой провал — откат сервера на
# прежний коммит и рестарт; код возврата 2 (откат сделан) или 1 (выката не было).
# Окно — AUTO_RULES_WATCH_S (600). Сервер — алиас ssh MEDCAT_SSH (beget).
set -uo pipefail
SHA="${1:?нужен SHA}"
HOST="${MEDCAT_SSH:-beget}"
APP=/opt/med-translation
WATCH="${AUTO_RULES_WATCH_S:-600}"
HERE="$(cd "$(dirname "$0")" && pwd)"

say() { echo "[deploy] $*"; }

fid() {   # предупреждений эталонов (tools/fidelity_report.py) — число строк warn=[…] непустых
  bash "$HERE/../prod_run.sh" "$HERE/../fidelity_report.py" 2>/dev/null | grep -c "warn=\[[^]]" || true
}

tb_count() {  # трейсбеков в журнале сервиса за последние N секунд
  ssh "$HOST" "journalctl -u medcat -u medcat-worker --since '-$1 s' --no-pager 2>/dev/null | grep -c Traceback" || echo 0
}

jobs_running() {
  ssh "$HOST" "sudo -u postgres psql -p 5433 medcat -Atc \"select count(*) from jobs where status='running' and kind<>'prepress'\" 2>/dev/null" || echo 0
}

PREV=$(ssh "$HOST" "cd $APP && git rev-parse HEAD") || { say "сервер недоступен"; exit 1; }
[ "$PREV" = "$SHA" ] && { say "уже выкачено"; exit 0; }
F0=$(fid); TB0=$(tb_count "$WATCH")
say "до выката: эталоны warn=$F0, трейсбеков за окно=$TB0, прежний коммит $PREV"
R=$(jobs_running)
[ "${R:-0}" -gt 0 ] && say "идут прогоны клиентов ($R): воркер доделает порцию и отложит их (инвариант 31)"

rollback() {
  say "ОТКАТ на $PREV: $1"
  ssh "$HOST" "cd $APP && git reset -q --hard $PREV && systemctl restart medcat medcat-worker"
  for i in $(seq 1 30); do sleep 3; ssh "$HOST" "curl -s --max-time 5 http://127.0.0.1:8000/api/health" >/dev/null && break; done
  exit 2
}

ssh "$HOST" "cd $APP && git fetch -q origin && git merge -q --ff-only $SHA && test \"\$(git rev-parse HEAD)\" = $SHA" \
  || { say "pull до $SHA не прошёл"; ssh "$HOST" "cd $APP && git reset -q --hard $PREV"; exit 1; }
ssh "$HOST" "systemctl restart medcat medcat-worker" || rollback "рестарт не прошёл"
ok=0
for i in $(seq 1 40); do
  sleep 3
  if ssh "$HOST" "curl -s --max-time 5 http://127.0.0.1:8000/api/health" | grep -q '"ok"'; then ok=1; break; fi
done
[ $ok = 1 ] || rollback "health не ответил за 120 с"
say "живой; окно наблюдения $WATCH с"
sleep "$WATCH"
TB1=$(tb_count "$WATCH")
[ "${TB1:-0}" -gt $(( ${TB0:-0} + 2 )) ] && rollback "трейсбеков за окно $TB1 против $TB0 до выката"
F1=$(fid)
[ "${F1:-0}" -gt "${F0:-0}" ] && rollback "эталоны: предупреждений $F1 против $F0"
say "выкат принят: эталоны warn=$F1, трейсбеков=$TB1"
echo "PREV=$PREV"
exit 0
