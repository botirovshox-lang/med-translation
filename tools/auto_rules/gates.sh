#!/usr/bin/env bash
# Рубеж «тесты» автоматического разбора (раздел Ы7): ВСЕ наборы Python и node
# по коду возврата (не по последней строке: печать бывает обманчива). Плюс
# фото-бенч, если на машине есть корпус (AUTO_RULES_CORPUS, вне репозитория).
# Набор, упавший один раз, перезапускается один раз в одиночку: часть тестов
# медленная и под нагрузкой машины падает по таймауту (test_layout_loop).
# Набор, падающий и на базе (`gates.sh BASE`), — прежняя беда, а не наша:
# он сверяется на выгрузке базы в отдельный каталог и прощается.
set -uo pipefail
export PYTHONIOENCODING=utf-8
BASE="${1:-}"
T="${AUTO_RULES_TEST_TIMEOUT:-900}"
bad=()
run() {
  timeout "$T" "$@" >/tmp/gate_$$.log 2>&1 && return 0
  timeout "$T" "$@" >/tmp/gate_$$.log 2>&1 && return 0
  echo "  FAIL $* :: $(tail -2 /tmp/gate_$$.log | tr '\n' ' ')"
  return 1
}
python -m py_compile backend/main.py || exit 1
for t in tests/test_*.py; do
  run python "$t" || bad+=("$t")
done
for t in tests/test_*.js; do
  case "$t" in *_browser.js) continue;; esac     # настоящий браузер — не на каждой машине
  run node "$t" || bad+=("$t")
done
if [ -n "${AUTO_RULES_CORPUS:-}" ] && [ -d "$AUTO_RULES_CORPUS" ]; then
  out=$(mktemp -d)
  run python tools/photo_bench.py "$AUTO_RULES_CORPUS" "$out" --check || bad+=("photo_bench")
  rm -rf "$out"
fi
rm -f /tmp/gate_$$.log
if [ ${#bad[@]} -gt 0 ] && [ -n "$BASE" ]; then
  B=$(mktemp -d)
  git archive "$BASE" backend tests tools frontend med_translation | tar -x -C "$B"
  still=()
  for t in "${bad[@]}"; do
    case "$t" in photo_bench) still+=("$t"); continue;; esac
    if (cd "$B" && case "$t" in *.js) timeout "$T" node "$t";; *) timeout "$T" python "$t";; esac >/dev/null 2>&1); then
      still+=("$t")                                  # на базе проходил — сломали мы
    else
      echo "  прощён (падает и на базе): $t"
    fi
  done
  rm -rf "$B"
  bad=("${still[@]}")
fi
if [ ${#bad[@]} -gt 0 ]; then
  echo "тесты не прошли: ${bad[*]}"
  exit 1
fi
echo "все тесты прошли"
