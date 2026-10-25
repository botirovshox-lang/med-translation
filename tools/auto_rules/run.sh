#!/usr/bin/env bash
# Автоматический разбор случаев проверки и первых выгрузок → правила → выкат
# (раздел Ы7, процедура — docs/rules/auto-rules.md). Запускается Планировщиком
# Windows раз в час (tools/auto_rules/install_task.ps1) или руками:
#   bash tools/auto_rules/run.sh            # по-настоящему
#   AUTO_RULES_DRY=1 bash tools/auto_rules/run.sh   # без пуша и выката
# Выключатель без правки кода: файл $STATE/OFF.
set -uo pipefail
REPO="${AUTO_RULES_REPO:-/c/Users/Shox/med_translation}"
STATE="${AUTO_RULES_STATE:-$HOME/.medcat-auto-rules}"
HOST="${MEDCAT_SSH:-beget}"
BUDGET="${AUTO_RULES_BUDGET_USD:-15}"
MODEL="${AUTO_RULES_MODEL:-claude-opus-5-5}"
DRY="${AUTO_RULES_DRY:-0}"
export PYTHONIOENCODING=utf-8
mkdir -p "$STATE/logs"
STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$STATE/logs/$STAMP.log"
exec > >(tee -a "$LOG") 2>&1
say() { echo "[auto-rules $(date +%H:%M:%S)] $*"; }
notify() {   # владельцу в Telegram — ключом самого сервера, без новой двери в API
  printf '%s' "$1" | ssh "$HOST" 'set -a; . /etc/medcat/env; set +a; [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && curl -s -o /dev/null --max-time 15 "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" -d chat_id="$TELEGRAM_ADMIN_CHAT" --data-urlencode text@-' || true
}

[ -e "$STATE/OFF" ] && { say "выключено ($STATE/OFF)"; exit 0; }
# Замок этой машины (атомарный mkdir; брошенный старше 8 ч снимается).
if ! mkdir "$STATE/lock" 2>/dev/null; then
  if [ -n "$(find "$STATE/lock" -maxdepth 0 -mmin +480 2>/dev/null)" ]; then rm -rf "$STATE/lock"; mkdir "$STATE/lock"; else say "уже идёт"; exit 0; fi
fi
# Замок между машинами — на сервере: владелец запускает сессии и с другой машины.
if ! ssh "$HOST" "mkdir /root/.medcat-auto-rules.lock 2>/dev/null || find /root/.medcat-auto-rules.lock -maxdepth 0 -mmin +480 -exec sh -c 'rmdir {} && mkdir {}' \;" 2>/dev/null; then
  say "разбор идёт на другой машине"; rmdir "$STATE/lock"; exit 0
fi
WT=""
cleanup() {
  ssh "$HOST" "rmdir /root/.medcat-auto-rules.lock" 2>/dev/null || true
  rmdir "$STATE/lock" 2>/dev/null || true
  if [ -n "$WT" ] && [ -d "$WT" ]; then
    git -C "$REPO" worktree remove --force "$WT" 2>/dev/null || powershell.exe -NoProfile -Command "Remove-Item -LiteralPath '\\\\?\\$(cygpath -w "$WT")' -Recurse -Force" 2>/dev/null
    git -C "$REPO" worktree prune 2>/dev/null
  fi
}
trap cleanup EXIT

cd "$REPO" || exit 1
NC=$(python tools/prepress_cases.py list --count 2>/dev/null | tail -1)
NR=$(python tools/export_review.py list --count 2>/dev/null | tail -1)
case "$NC$NR" in *[!0-9]*|"") say "очередь не прочиталась (cases=$NC reviews=$NR)"; exit 1;; esac
if [ "$NC" -eq 0 ] && [ "$NR" -eq 0 ]; then say "очередь пуста"; exit 0; fi
python tools/auto_rules/guard.py quota "$STATE" || { say "потолок выкатов на сегодня"; exit 0; }
say "в очереди: случаев $NC, первых выгрузок $NR"

git fetch -q origin || exit 1
BASE=$(git rev-parse origin/main)
WT="$STATE/wt-$STAMP"
BR="auto-rules/$STAMP"
git -c core.longpaths=true worktree add -q -b "$BR" "$WT" "$BASE" || exit 1
mkdir -p "$WT/.auto-rules"
cd "$WT"

say "агент разбирает (модель $MODEL, потолок \$$BUDGET)"
claude -p "$(cat docs/rules/auto-rules-agent.md)" \
  --model "$MODEL" --max-budget-usd "$BUDGET" --permission-mode acceptEdits \
  --allowedTools "Read" "Edit" "Write" "Glob" "Grep" "Agent" \
     "Bash(python *)" "Bash(node *)" "Bash(git diff*)" "Bash(git status*)" "Bash(git log*)" \
     "Bash(git add*)" "Bash(git commit*)" "Bash(git show*)" "Bash(ls*)" "Bash(cat *)" \
     "Bash(mkdir *)" \
  --disallowedTools "Bash(git push*)" "Bash(ssh *)" "Bash(scp *)" "Bash(git reset*)" "Bash(git checkout*)"      "Bash(bash tools/prod_run.sh*)" "Bash(rm *)" \
  --output-format text > ".auto-rules/agent.txt" 2>&1
RC=$?
tail -40 ".auto-rules/agent.txt"
RES="$WT/.auto-rules/result.json"
[ -f "$RES" ] || { say "агент не оставил отчёта (rc=$RC)"; notify "🤖 Автоправила: агент не дописал разбор (лог $LOG)"; exit 1; }
STATUS=$(python -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('status'))" "$RES")
if [ "$STATUS" = "nothing" ] || [ "$STATUS" = "held" ]; then
  say "агент: $STATUS"; python - "$RES" <<'PY'
import json, subprocess, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
for c in r.get("cases") or []:          # «не наш брак» и отложенное — с причиной
    if c.get("verdict") in ("wont", "held"):
        subprocess.run([sys.executable, "tools/prepress_cases.py", "wont", c["tenant"], str(c["pid"]),
                        str(c["n"]), "--note", (c.get("note") or c["verdict"])[:200]])
PY
  exit 0
fi

# Рубежи — код, а не модель.
HEAD=$(git rev-parse HEAD)
python tools/auto_rules/guard.py result "$RES" || { notify "🤖 Автоправила: отказ рубежа (отчёт агента), лог $LOG"; exit 1; }
python tools/auto_rules/guard.py diff "$BASE" "$HEAD" || { notify "🤖 Автоправила: отказ рубежа (дифф), лог $LOG"; exit 1; }
say "полный прогон тестов"
bash tools/auto_rules/gates.sh "$BASE" || { notify "🤖 Автоправила: тесты не прошли, выката нет. Лог $LOG"; exit 1; }

if [ "$DRY" = "1" ]; then say "сухой режим: ветка $BR готова, выката нет"; notify "🤖 Автоправила (сухой режим): ветка $BR готова"; exit 0; fi

git fetch -q origin
if [ "$(git rev-parse origin/main)" != "$BASE" ]; then
  say "main уехал — перенос и повтор тестов"
  git rebase -q origin/main || { git rebase --abort; notify "🤖 Автоправила: конфликт с main, выката нет"; exit 1; }
  BASE=$(git rev-parse origin/main)
  HEAD=$(git rev-parse HEAD)
  python tools/auto_rules/guard.py diff "$BASE" "$HEAD" || { notify "🤖 Автоправила: отказ рубежа после переноса"; exit 1; }
  bash tools/auto_rules/gates.sh "$BASE" || { notify "🤖 Автоправила: тесты после переноса не прошли"; exit 1; }
fi
git push -q origin "$HEAD:refs/heads/main" || { notify "🤖 Автоправила: пуш не прошёл"; exit 1; }
say "выкат $HEAD"
OUT=$(bash tools/auto_rules/deploy.sh "$HEAD"); DRC=$?
echo "$OUT"
PREV=$(echo "$OUT" | sed -n 's/^PREV=//p' | tail -1)
SUMMARY=$(python -c "import json,sys;r=json.load(open(sys.argv[1],encoding='utf-8'));print('; '.join((x.get('id','')+' '+x.get('title',''))[:90] for x in r.get('rules') or []))" "$RES")
if [ $DRC -eq 2 ]; then
  # Сервер уже откатан; main тоже возвращаем, иначе следующий ручной выкат привезёт то же.
  git revert -q --no-edit "$BASE..$HEAD" && git push -q origin "HEAD:refs/heads/main"
  python tools/auto_rules/guard.py note "$STATE" "$HEAD" "$PREV" rolledback
  notify "🤖 Автоправила: выкат ОТКАЧЕН (проверка после выката). Правила: $SUMMARY. Лог $LOG"
  exit 1
fi
[ $DRC -ne 0 ] && { notify "🤖 Автоправила: выкат не состоялся. Лог $LOG"; exit 1; }
python tools/auto_rules/guard.py note "$STATE" "$HEAD" "$PREV" deployed
python - "$RES" "$HEAD" <<'PY'
import json, subprocess, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
for c in r.get("cases") or []:
    v = c.get("verdict")
    if v in ("done", "wont"):
        cmd = [sys.executable, "tools/prepress_cases.py", v, c["tenant"], str(c["pid"]), str(c["n"]),
               "--note", (c.get("note") or "")[:200] + " (" + sys.argv[2][:8] + ")"]
        if v == "done":
            cmd += ["--rule", c.get("rule") or "?"]
        subprocess.run(cmd)
for rv in r.get("reviews") or []:
    if rv.get("verdict") == "done":
        subprocess.run([sys.executable, "tools/export_review.py", "done", str(rv["rid"]),
                        "--report", rv.get("report") or "auto-rules", "--note", (rv.get("note") or "")[:200]])
PY
notify "🤖 Автоправила выкачены ($(echo $HEAD | cut -c1-8)): $SUMMARY. Критики: ок, тесты и эталоны не хуже."
say "готово"
