#!/bin/sh
# Замок автоматического разбора (раздел Ы7): один разбор за раз — и между
# машинами владельца (замок лежит на сервере), и на одной машине.
#   sh lock.sh acquire DIR     # 0 — взят, 1 — занят
#   sh lock.sh release DIR
# Атомарность — `mkdir`; брошенный старше AUTO_RULES_LOCK_MIN минут (480)
# снимается и берётся заново. Запускается и локально, и `ssh host sh -s`.
cmd="$1"; dir="$2"; ttl="${3:-480}"
[ -n "$dir" ] || exit 2
case "$cmd" in
  acquire)
    if mkdir "$dir" 2>/dev/null; then exit 0; fi
    if [ -n "$(find "$dir" -maxdepth 0 -mmin +"$ttl" 2>/dev/null)" ]; then
      rmdir "$dir" 2>/dev/null && mkdir "$dir" 2>/dev/null && exit 0
    fi
    exit 1 ;;
  release)
    rmdir "$dir" 2>/dev/null
    exit 0 ;;
  *) exit 2 ;;
esac
