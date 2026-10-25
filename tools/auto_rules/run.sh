#!/usr/bin/env bash
# Автоматический разбор случаев проверки и первых выгрузок → правила → выкат
# (раздел Ы7, процедура — docs/rules/auto-rules.md). Планировщик Windows раз
# в час (tools/auto_rules/install_task.ps1) или руками:
#   bash tools/auto_rules/run.sh                     # по-настоящему
#   AUTO_RULES_DRY=1 bash tools/auto_rules/run.sh    # без пуша и выката
# Выключатель без правки кода: файл $STATE/OFF (его же ставит любой откат).
#
# ДОВЕРЕННЫЙ КОД. Всё, что проверяет и выкатывает (этот файл, guard, gates,
# deploy, инструменты очереди, эталоны), берётся из origin/main в отдельный
# каталог ДО запуска агента и исполняется оттуда: агент правит своё дерево,
# а судят его скриптами, которых он не касался (критик 25.10.2026).
set -uo pipefail
REPO="${AUTO_RULES_REPO:-/c/Users/Shox/med_translation}"
STATE="${AUTO_RULES_STATE:-$HOME/.medcat-auto-rules}"
HOST="${MEDCAT_SSH:-beget}"
export PYTHONIOENCODING=utf-8 MEDCAT_SSH="$HOST"
mkdir -p "$STATE/logs" "$STATE/results"

if [ -z "${AUTO_RULES_TRUSTED:-}" ]; then
  [ -e "$STATE/OFF" ] && { echo "[auto-rules] выключено ($STATE/OFF)"; exit 0; }
  git -C "$REPO" fetch -q origin || exit 1
  SHA=$(git -C "$REPO" rev-parse origin/main)
  T="$STATE/trusted-${SHA:0:12}"
  if [ ! -d "$T" ]; then
    D="$T.tmp.$$"
    mkdir -p "$D" && git -C "$REPO" archive "$SHA" tools docs/rules/auto-rules-agent.md | tar -x -C "$D" \
      && { mv "$D" "$T" 2>/dev/null || rm -rf "$D"; } || { rm -rf "$D"; exit 1; }
  fi
  # Старые копии — только старше суток и не текущая: идущий разбор (он мог
  # начаться с прежнего main и сейчас выкатывать) ещё зовёт свои скрипты.
  find "$STATE" -maxdepth 1 -name 'trusted-*' -mtime +1 ! -path "$T" -exec rm -rf {} + 2>/dev/null
  AUTO_RULES_TRUSTED="$T" AUTO_RULES_BASE="$SHA" exec bash "$T/tools/auto_rules/run.sh" "$@"
fi

T="$AUTO_RULES_TRUSTED"
BASE="$AUTO_RULES_BASE"
G="$T/tools/auto_rules"
BUDGET="${AUTO_RULES_BUDGET_USD:-15}"
MODEL="${AUTO_RULES_MODEL:-claude-opus-5-5}"
DRY="${AUTO_RULES_DRY:-0}"
STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$STATE/logs/$STAMP.log"
exec > >(tee -a "$LOG") 2>&1
say() { echo "[auto-rules $(date +%H:%M:%S)] $*"; }
notify() {   # владельцу в Telegram — ключом самого сервера, без новой двери в API
  printf '%s' "$1" | ssh "$HOST" 'set -a; . /etc/medcat/env; set +a; [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && curl -s -o /dev/null --max-time 15 "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" -d chat_id="$TELEGRAM_ADMIN_CHAT" --data-urlencode text@-' || true
}
stop_all() {  # после отката или неясного состояния — до человека
  touch "$STATE/OFF"
  notify "🤖 Автоправила ВЫКЛЮЧЕНЫ до человека: $1. Включить — удалить $STATE/OFF. Лог $LOG"
}

sh "$G/lock.sh" acquire "$STATE/lock" || { say "уже идёт"; exit 0; }
if ! ssh "$HOST" "sh -s acquire /root/.medcat-auto-rules.lock" < "$G/lock.sh"; then
  say "разбор идёт на другой машине"; sh "$G/lock.sh" release "$STATE/lock"; exit 0
fi
WT=""
DATA=""
cleanup() {
  ssh "$HOST" "sh -s release /root/.medcat-auto-rules.lock" < "$G/lock.sh" 2>/dev/null || true
  sh "$G/lock.sh" release "$STATE/lock"
  [ -n "$DATA" ] && rm -rf "$DATA"                  # данные клиента — не хранить
  if [ -n "$WT" ] && [ -d "$WT" ]; then
    git -C "$REPO" worktree remove --force "$WT" 2>/dev/null || powershell.exe -NoProfile -Command "Remove-Item -LiteralPath '\\\\?\\$(cygpath -w "$WT")' -Recurse -Force" 2>/dev/null
    git -C "$REPO" worktree prune 2>/dev/null
  fi
}
trap cleanup EXIT

cd "$REPO" || exit 1
NC=$(python "$T/tools/prepress_cases.py" list --count 2>/dev/null | tail -1)
NR=$(python "$T/tools/export_review.py" list --count 2>/dev/null | tail -1)
case "$NC$NR" in *[!0-9]*|"") say "очередь не прочиталась (cases=$NC reviews=$NR)"; exit 1;; esac
if [ "$NC" -eq 0 ] && [ "$NR" -eq 0 ]; then say "очередь пуста"; exit 0; fi
python "$G/guard.py" quota "$STATE" || { say "потолок выкатов на сегодня"; exit 0; }
python "$G/guard.py" runs "$STATE" || { say "потолок запусков агента на сегодня"; exit 0; }
say "в очереди: случаев $NC, первых выгрузок $NR"

# Данные клиента скачивает РАННЕР: агенту ssh не нужен вовсе.
DATA=$(mktemp -d)
python "$T/tools/prepress_cases.py" pull "$DATA/cases" || { say "случаи не скачались"; exit 1; }
python "$T/tools/export_review.py" list --json > "$DATA/reviews.json" 2>/dev/null || echo "[]" > "$DATA/reviews.json"
python - "$DATA" "$T" <<'PY'
import json, subprocess, sys
d, t = sys.argv[1], sys.argv[2]
for r in json.load(open(d + "/reviews.json", encoding="utf-8")) or []:
    dst = "%s/review-%s" % (d, r["id"])
    if subprocess.run([sys.executable, t + "/tools/export_review.py", "fetch", str(r["project"]), dst]).returncode == 0:
        subprocess.run([sys.executable, t + "/tools/export_review.py", "pages", dst])
PY
# Случаи, которые разбирали уже AUTO_RULES_CASE_TRIES раз, — человеку (не жечь деньги кругами).
python "$G/guard.py" attempts "$STATE" "$DATA" "$T"
LEFT=$(ls "$DATA/cases"/*.json 2>/dev/null | wc -l)
NREV=$(python -c "import json,sys;print(len(json.load(open(sys.argv[1],encoding='utf-8'))))" "$DATA/reviews.json")
if [ "$LEFT" -eq 0 ] && [ "$NREV" -eq 0 ]; then say "всё оставшееся — человеку"; exit 0; fi

WT="$STATE/wt-$STAMP"
BR="auto-rules/$STAMP"
git -c core.longpaths=true worktree add -q -b "$BR" "$WT" "$BASE" || exit 1
cd "$WT"
RES="$STATE/results/$STAMP.json"
ALOG="$STATE/logs/$STAMP.agent.txt"
PROMPT="$(cat "$T/docs/rules/auto-rules-agent.md")

Данные клиента уже скачаны раннером в каталог $DATA (случаи — cases/, первые выгрузки — review-<id>/ c парами в pairs/; список — reviews.json). Отчёт пиши в файл $RES. Корпус фото-бенча: ${AUTO_RULES_CORPUS:-нет на этой машине}."

say "агент разбирает (модель $MODEL, потолок \$$BUDGET)"
# Пушит только раннер: у git агента адрес отправки — пустышка (через окружение,
# без правки конфига репозитория владельца).
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.pushurl GIT_CONFIG_VALUE_0="no-push://auto-rules" \
claude -p "$PROMPT" --model "$MODEL" --max-budget-usd "$BUDGET" --permission-mode acceptEdits \
  --add-dir "$DATA" --add-dir "$STATE/results" \
  --allowedTools "Read" "Edit" "Write" "Glob" "Grep" "Agent" \
     "Bash(python *)" "Bash(node *)" "Bash(git diff*)" "Bash(git status*)" "Bash(git log*)" \
     "Bash(git add*)" "Bash(git commit*)" "Bash(git show*)" "Bash(ls*)" "Bash(cat *)" "Bash(mkdir *)" \
  --disallowedTools "Bash(git push*)" "Bash(ssh *)" "Bash(scp *)" "Bash(git reset*)" "Bash(git checkout*)" \
     "Bash(git config*)" "Bash(bash tools/prod_run.sh*)" "Bash(rm *)" "Bash(curl *)" \
     "Edit($REPO/**)" "Write($REPO/**)" "Edit($T/**)" "Write($T/**)" \
     "Edit($STATE/*.sh)" "Write($STATE/*.sh)" "Edit($STATE/*.json)" "Write($STATE/*.json)" \
  --output-format text > "$ALOG" 2>&1
RC=$?
tail -30 "$ALOG"
[ -f "$RES" ] || { say "агент не оставил отчёта (rc=$RC)"; notify "🤖 Автоправила: агент не дописал разбор (лог $LOG)"; exit 1; }
STATUS=$(python -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('status'))" "$RES" 2>/dev/null)
if [ "$STATUS" = "nothing" ] || [ "$STATUS" = "held" ]; then
  say "агент: $STATUS"
  python "$G/guard.py" mark "$RES" "$T" "" wontonly
  exit 0
fi

# Рубежи — доверенный код, а не модель. Дерево обязано быть чистым: иначе
# тесты шли бы на одном коде, а в прод ушёл бы другой.
if [ -n "$(git status --porcelain)" ]; then
  notify "🤖 Автоправила: агент оставил незакоммиченное — выката нет. Лог $LOG"; exit 1
fi
HEAD=$(git rev-parse HEAD)
python "$G/guard.py" result "$RES" || { notify "🤖 Автоправила: отказ рубежа (отчёт агента), лог $LOG"; exit 1; }
python "$G/guard.py" diff "$BASE" "$HEAD" || { notify "🤖 Автоправила: отказ рубежа (дифф), лог $LOG"; exit 1; }
say "полный прогон тестов"
bash "$G/gates.sh" "$BASE" || { notify "🤖 Автоправила: тесты не прошли, выката нет. Лог $LOG"; exit 1; }

if [ "$DRY" = "1" ]; then say "сухой режим: ветка $BR готова, выката нет"; notify "🤖 Автоправила (сухой режим): ветка $BR готова"; exit 0; fi

ORIGIN=$(git remote get-url origin)
git fetch -q origin
if [ "$(git rev-parse origin/main)" != "$BASE" ]; then
  say "main уехал — перенос и повтор рубежей"
  git rebase -q origin/main || { git rebase --abort; notify "🤖 Автоправила: конфликт с main, выката нет"; exit 1; }
  BASE=$(git rev-parse origin/main)
  HEAD=$(git rev-parse HEAD)
  python "$G/guard.py" diff "$BASE" "$HEAD" || { notify "🤖 Автоправила: отказ рубежа после переноса"; exit 1; }
  bash "$G/gates.sh" "$BASE" || { notify "🤖 Автоправила: тесты после переноса не прошли"; exit 1; }
fi
git push -q "$ORIGIN" "$HEAD:refs/heads/main" || { notify "🤖 Автоправила: пуш не прошёл"; exit 1; }
say "выкат $HEAD"
OUT=$(bash "$G/deploy.sh" "$HEAD"); DRC=$?
echo "$OUT"
PREV=$(echo "$OUT" | sed -n 's/^PREV=//p' | tail -1)
SUMMARY=$(python -c "import json,sys;r=json.load(open(sys.argv[1],encoding='utf-8'));print('; '.join((x.get('id','')+' '+x.get('title',''))[:90] for x in r.get('rules') or []))" "$RES")
if [ $DRC -ne 0 ]; then
  # Сервер откатан (2) либо выкат не состоялся (1) — main тоже возвращаем,
  # иначе следующий запуск и следующий ручной выкат привезли бы то же.
  python "$G/guard.py" note "$STATE" "$HEAD" "$PREV" "failed$DRC"
  if git revert -q --no-edit "$BASE..$HEAD" && git push -q "$ORIGIN" "HEAD:refs/heads/main"; then
    stop_all "выкат не принят (код $DRC), main возвращён ревёртом. Правила: $SUMMARY"
  else
    stop_all "выкат не принят (код $DRC), а ревёрт main НЕ ПРОШЁЛ — в main лежит невыкаченное $HEAD"
  fi
  exit 1
fi
python "$G/guard.py" note "$STATE" "$HEAD" "$PREV" deployed
python "$G/guard.py" mark "$RES" "$T" "${HEAD:0:8}" all
notify "🤖 Автоправила выкачены (${HEAD:0:8}): $SUMMARY. Критики: ок, тесты и эталоны не хуже."
say "готово"
