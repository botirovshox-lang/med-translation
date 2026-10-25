#!/usr/bin/env bash
# Выкат коммита на боевой сервер с проверкой и АВТООТКАТОМ (раздел Ы7).
#   bash tools/auto_rules/deploy.sh SHA
# Порядок: эталоны ДО (упал замер — выката нет) → на сервере ставится
# СТОРОЖ: таймер systemd откатит на прежний коммит, если выкат не подтвердят
# за AUTO_RULES_GUARD_MIN минут (оборвалась сеть, выключилась машина
# владельца) → pull ровно до SHA → рестарт → здоровье → окно наблюдения
# (трейсбеков не больше, чем до +2) → эталоны ПОСЛЕ (упал замер или
# предупреждений больше — откат) → снять сторожа.
# Код возврата: 0 — принят, 2 — откачен, 1 — выката не было.
set -uo pipefail
SHA="${1:?нужен SHA}"
HOST="${MEDCAT_SSH:-beget}"
APP=/opt/med-translation
WATCH="${AUTO_RULES_WATCH_S:-600}"
FID_S="${AUTO_RULES_FID_TIMEOUT_S:-1200}"
# Сторож обязан пережить ВСЮ проверку: окно + замер + запас 15 минут,
# иначе он откатил бы выкат посреди замера.
GUARD_MIN="${AUTO_RULES_GUARD_MIN:-$(( (WATCH + FID_S) / 60 + 30 ))}"
HERE="$(cd "$(dirname "$0")" && pwd)"
MARK=/root/.medcat-deploy-pending

say() { echo "[deploy] $*"; }

fid() {   # число предупреждений эталонов или ERR (замер упал)
  timeout "$FID_S" bash "$HERE/../prod_run.sh" "$HERE/../fidelity_report.py" 2>&1 | python "$HERE/guard.py" fid
}

tb_count() {  # трейсбеков в журнале сервиса за последние N минут
  ssh "$HOST" "journalctl -u medcat -u medcat-worker --since '$1 min ago' --no-pager 2>/dev/null | grep -c Traceback" | tail -1
}

PREV=$(ssh "$HOST" "cd $APP && git rev-parse HEAD") || { say "сервер недоступен"; exit 1; }
[ "$PREV" = "$SHA" ] && { say "уже выкачено"; exit 0; }
F0=$(fid) || { say "замер эталонов ДО не удался — выката нет"; exit 1; }
WM=$(( (WATCH + 59) / 60 ))
TB0=$(tb_count "$WM"); TB0=${TB0:-0}
say "до выката: предупреждений эталонов $F0, трейсбеков за $WM мин $TB0, прежний коммит $PREV"

rollback() {
  say "ОТКАТ на $PREV: $1"
  ssh "$HOST" "cd $APP && git reset -q --hard $PREV && systemctl restart medcat medcat-worker; rm -f $MARK; systemctl stop medcat-deploy-guard.timer 2>/dev/null"
  for i in $(seq 1 30); do sleep 3; ssh "$HOST" "curl -s --max-time 5 http://127.0.0.1:8000/api/health" | grep -q '"ok"' && break; done
  exit 2
}

# Сторож на сервере — до первой правки.
ssh "$HOST" "echo $PREV > $MARK && systemctl stop medcat-deploy-guard.timer 2>/dev/null; \
  systemd-run --quiet --unit medcat-deploy-guard --on-active=${GUARD_MIN}m /bin/sh -c \
  'test -f $MARK && cd $APP && git reset -q --hard \$(cat $MARK) && systemctl restart medcat medcat-worker && rm -f $MARK'" \
  || { say "сторож на сервере не встал — выката нет"; exit 1; }

ssh "$HOST" "cd $APP && git fetch -q origin && git merge -q --ff-only $SHA && test \"\$(git rev-parse HEAD)\" = $SHA" \
  || { say "pull до $SHA не прошёл"; ssh "$HOST" "cd $APP && git reset -q --hard $PREV; rm -f $MARK; systemctl stop medcat-deploy-guard.timer 2>/dev/null"; exit 1; }
ssh "$HOST" "systemctl restart medcat medcat-worker" || rollback "рестарт не прошёл"
ok=0
for i in $(seq 1 40); do
  sleep 3
  if ssh "$HOST" "curl -s --max-time 5 http://127.0.0.1:8000/api/health" | grep -q '"ok"'; then ok=1; break; fi
done
[ $ok = 1 ] || rollback "health не ответил за 120 с"
say "живой; окно наблюдения $WATCH с"
sleep "$WATCH"
TB1=$(tb_count "$WM"); TB1=${TB1:-0}
case "$TB1$TB0" in *[!0-9]*) rollback "журнал не прочитан ($TB1/$TB0)";; esac
[ "$TB1" -gt $(( TB0 + 2 )) ] && rollback "трейсбеков за окно $TB1 против $TB0 до выката"
F1=$(fid) || rollback "замер эталонов ПОСЛЕ не удался"
[ "$F1" -gt "$F0" ] && rollback "эталоны: предупреждений $F1 против $F0"
ssh "$HOST" "rm -f $MARK; systemctl stop medcat-deploy-guard.timer 2>/dev/null" || rollback "сторожа не снять"
say "выкат принят: предупреждений эталонов $F1, трейсбеков $TB1"
echo "PREV=$PREV"
exit 0
