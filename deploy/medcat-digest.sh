#!/bin/sh
# Суточная сводка метрик владельцу в Telegram (инвариант 34).
#
# Что это. `GET /api/admin/metrics` сводит пять источников — счётчики событий,
# расход по проектам, журнал токенов, страницы организаций и сметы — и отвечает
# на вопрос «где теряем деньги, где можно заработать, что чинить».
# `…/digest/send` присылает тот же разбор словами тем же ботом, что и остальные
# уведомления сервиса (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_ADMIN_CHAT`).
#
# Ставится в cron root'а (сервер живёт по UTC, 04:00 UTC = 09:00 в Ташкенте):
#   0 4 * * * /usr/local/bin/medcat-digest.sh >> /var/log/medcat-digest.log 2>&1
#
# Почему через HTTP, а не отдельным процессом с импортом main.py: третий
# процесс запрещён (инвариант 1) — кэши глоссария и разбора живут в памяти
# API, а STATE у чужого процесса свой. Здесь же работает ровно та дорога,
# которой ходит кнопка «Прислать в Telegram» на вкладке «Метрики»: один вход,
# один POST, один выход. Никакой своей логики у скрипта нет и быть не должно —
# разойдись она с кнопкой, и письмо говорило бы не то, что экран.
#
# Пароля в кроне нет: он берётся из /etc/medcat/env, который и так читает
# только root. Оговорка названа честно — APP_PASSWORD совпадает с паролем
# владельца `admin`, только пока тот его не менял (CLAUDE.md, «Деплой»).
# Сменит — сводка перестанет уходить, и скрипт скажет об этом строкой
# в журнале, а не замолчит.
set -eu

ENV=${MEDCAT_ENV:-/etc/medcat/env}
API=${MEDCAT_API:-http://127.0.0.1:8000}
LOGIN=${MEDCAT_DIGEST_LOGIN:-admin}
DAYS=${1:-1}
OUT=$(mktemp)
trap 'rm -f "$OUT"' EXIT
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') medcat-digest: $*"; }

[ -r "$ENV" ] || { say "не читается $ENV" >&2; exit 1; }
# Значение берём как есть, до конца строки: в пароле законны и пробелы,
# и знаки препинания. Кавычки по краям снимаем — systemd их допускает.
PASS=$(sed -n 's/^APP_PASSWORD=//p' "$ENV" | head -1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")
[ -n "$PASS" ] || { say "в $ENV нет APP_PASSWORD — отправлять некем" >&2; exit 1; }

# Тело запроса собирает python3, а не printf: пароль со скобкой, кавычкой
# или обратной косой иначе развалил бы JSON, и вход молча отвечал бы 422.
# Через stdin, а не аргументом, — аргументы видны в списке процессов.
BODY=$(LOGIN="$LOGIN" PASS="$PASS" python3 -c 'import json,os; print(json.dumps({"login":os.environ["LOGIN"],"password":os.environ["PASS"]}))')
TOKEN=$(printf '%s' "$BODY" |
    curl -sS -m 20 -H 'Content-Type: application/json' --data-binary @- "$API/api/auth/login" 2>/dev/null |
    python3 -c 'import sys,json; print(json.load(sys.stdin).get("token") or "")' 2>/dev/null || true)
if [ -z "$TOKEN" ]; then
    say "вход как «$LOGIN» не удался: пароль в $ENV не совпадает с нынешним" >&2
    exit 1
fi

CODE=$(curl -sS -m 60 -o "$OUT" -w '%{http_code}' -X POST \
       -H "Authorization: Bearer $TOKEN" \
       "$API/api/admin/metrics/digest/send?days=$DAYS" || echo 000)
# Сессию за собой закрываем: живут они по SESSION_TTL_HOURS, и ежедневный
# вход, который никто не закрывает, — это мусор в памяти процесса.
curl -sS -m 10 -X POST -H "Authorization: Bearer $TOKEN" "$API/api/auth/logout" >/dev/null 2>&1 || true

if [ "$CODE" = "200" ]; then
    say "сводка за $DAYS сут. отправлена"
else
    say "не отправлено (HTTP $CODE): $(head -c 300 "$OUT")" >&2
    exit 1
fi
