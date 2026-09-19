#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пересобрать сегменты проекта из ЕГО ЖЕ исходника по нынешним правилам разбора.

Зачем. Правила разбора меняются (PDF: колонтитулы, врезки, подписи, перенос
через границу страницы — `backend/pdftext.py`), а проект, загруженный раньше,
хранит сегменты, нарезанные старыми правилами: «кон- В продаже на рынках…»
так и остаётся одним сегментом. Загружать файл заново — терять оплаченный
перевод неизменившихся строк. Этот инструмент делает то же, что «Заменить
файл» (`/api/projects/{pid}/reimport`), но файлом служит сохранённый исходник
проекта, и:
  * страницы НЕ списываются (`_pages_debit` на время вызова — ноль, объём
    проекта `pages` остаётся прежним): это не новая работа клиента, а наша
    переделка разбора;
  * сегмент, текст которого не изменился (ключ `_match_key`: пробелы
    и регистр не в счёт), остаётся целиком — перевод, статус, проверки;
  * сегмент, текст которого изменился, заводится заново (статус new, перевод
    пуст), а прежний перевод перекрывавшихся старых сегментов кладётся
    в `prevTarget` (и их текст — в `prevSource`), чтобы человек собрал
    новый перевод из готового, а не переводил заново;
  * сегменты с картинок остаются на месте, если картинки собранного .docx
    не изменились (те же части пакета, те же байты); иначе — как у замены
    файла: уходят в копию, разбор картинок заведёт их заново бесплатно;
  * копия прежнего состояния и откат — те же, что у замены файла
    (`data/backups/reimport-{pid}-{stamp}.*`, `/reimport/{stamp}/undo`).

Где исходник. У .docx проекта — `data/sources/{pid}.docx` (он и есть
присланный файл); у остальных форматов — оригинал `data/sources/{pid}.orig.<ext>`
(`_store_original`). Нет ни того ни другого (проект старше хранения
оригиналов) — файл называется аргументом `--file`.

Инварианты. Пишет ТОЛЬКО через код приложения (`_reimport_apply` →
`save_state`, версия документа проекта, копия до правки). С базой (DATABASE_URL)
после записи поднимается эпоха `doc:projects:N` — API перечитает проект, как
после прогона воркера. С файлом `state.json` второй пишущий процесс запрещён
(инвариант 1): запись (`--apply`) — только при ОСТАНОВЛЕННОМ сервисе и с
флагом `--offline`. Идущий или ждущий прогон по проекту — отказ.

Запуск (на сервере — с окружением сервиса):
    python3 tools/resegment_project.py 12                # сухой прогон: числа
    python3 tools/resegment_project.py 12 --apply        # запись
    python3 tools/resegment_project.py 12 --file book.pdf --apply
Код возврата: 0 — готово (или сухой прогон), 1 — отказ с причиной.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Доля общих слов, при которой старый сегмент считается «тем же местом»
# нового: от меньшего из двух (кусок, отрезанный от длинного абзаца, целиком
# лежит в нём).
PREV_OVERLAP = 0.5


class Refuse(Exception):
    pass


def load_main():
    """Приложение — как у воркера прогонов: роль worker ДО импорта. Иначе
    импорт прогнал бы миграции старта, которые пишут состояние (их пишет
    только API), а сторож 409 спрашивал бы зеркало задач этого процесса —
    пустое. Идущий прогон проверяется прямо по таблице задач (`apply_plan`)."""
    os.environ["MEDCAT_ROLE"] = "worker"
    os.environ.setdefault("APP_PASSWORD", os.environ.get("APP_PASSWORD") or "resegment-tool")
    sys.path.insert(0, str(ROOT / "backend"))
    import main  # noqa: E402
    return main


def find_project(main, pid: int) -> dict:
    """Проект по номеру во ВСЕХ организациях (инструмент — не запрос
    пользователя) и сессия его организации: `get_project` дальше видит его."""
    for p in main.STATE.get("projects") or []:
        if p.get("id") == pid:
            main.CURRENT_SESSION.set({"tenant": main._tenant_of(p), "user": None, "role": "owner"})
            return p
    raise Refuse("Проекта %d нет" % pid)


def source_of(main, project: dict, file_arg=None) -> tuple:
    """(имя файла, байты, откуда) — исходник проекта."""
    if file_arg:
        p = Path(file_arg)
        if not p.exists():
            raise Refuse("Файла %s нет" % p)
        return p.name, p.read_bytes(), str(p)
    pid = project["id"]
    orig = main._orig_existing(pid)
    name = project.get("fileName") or ""
    if orig is not None:
        ext = orig.suffix.lower()
        if not name.lower().endswith(ext):
            name = "source" + ext
        return name, orig.read_bytes(), str(orig)
    docx_path, _map = main._source_paths(pid)
    if docx_path.exists() and (name.lower().endswith(".docx") or not project.get("importKind")
                               or project.get("importKind") == "docx"):
        return (name if name.lower().endswith(".docx") else "source.docx"), docx_path.read_bytes(), str(docx_path)
    raise Refuse("У проекта %d нет сохранённого оригинала (%s): загружен до хранения "
                 "оригиналов или из формата, у которого хранится только собранный .docx. "
                 "Назовите файл: --file ПУТЬ" % (pid, name or "имя неизвестно"))


def _words(t: str) -> set:
    return set(re.findall(r"\w+", (t or "").lower()))


def resegment(main, pid: int, file_arg=None, apply=False, offline=False) -> dict:
    """Весь путь инструмента; бросает `Refuse` с причиной. Ядро — то же,
    что у кнопки «Пересобрать строки» (`main._resegment_plan` /
    `main._resegment_apply`): две копии правила разошлись бы."""
    if apply and getattr(main.STORE, "kind", "file") != "pg" and not offline:
        raise Refuse("Хранилище — файл state.json: второй пишущий процесс рядом с сервисом "
                     "затёр бы его запись (инвариант 1). Остановите сервис и повторите "
                     "с --offline — или запускайте на сервере с DATABASE_URL.")
    if getattr(main.STORE, "kind", "") == "pg":
        key = "projects:%d" % pid
        try:
            main._apply_doc(key, main.STORE.load_doc(key))   # свежий документ проекта
        except Exception as e:
            raise Refuse("Документ проекта не перечитан из базы: %s" % e)
    project = find_project(main, pid)
    filename, content, where = source_of(main, project, file_arg)
    try:
        parsed = main._resegment_parse(filename, content)
    except Exception as e:
        raise Refuse("Исходник не разобрался (%s): %s" % (where, e))
    if not parsed["units"]:
        raise Refuse("В исходнике не нашлось ни одной строки текста — пересобирать нечего")
    pl = main._resegment_plan(project, parsed)
    out = {"project": pid, "file": where, "kind": parsed["kind"], "dryRun": not apply,
           **pl["counts"], "samples": pl["samples"], "removedSample": pl["removedSample"]}
    if apply:
        # Процесс инструмента — с ролью worker: зеркало задач пустое, поэтому
        # идущий прогон спрашивается прямо у таблицы задач базы.
        jid = main._active_job_for(pid)
        if not jid:
            try:
                jid = main.STORE.active_job_for(pid)
            except Exception as e:
                raise Refuse("Не проверить, идёт ли прогон по проекту: %s" % e)
        if jid or main._job_busy(pid, "images"):
            raise Refuse("По проекту идёт или ждёт прогон №%s — пересборка подождёт его конца" % jid)
        try:
            out.update(main._resegment_apply(pid, parsed, content, filename, pl))
        except main.HTTPException as e:
            raise Refuse(str(e.detail))
    return out


def main_cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Пересобрать сегменты проекта из его исходника")
    ap.add_argument("project", type=int, help="номер проекта")
    ap.add_argument("--file", help="исходник, если оригинал проекта не сохранён")
    ap.add_argument("--apply", action="store_true", help="записать (по умолчанию — только числа)")
    ap.add_argument("--offline", action="store_true",
                    help="сервис остановлен (нужно для записи при хранилище state.json)")
    ap.add_argument("--json", action="store_true", help="ответ одним JSON")
    a = ap.parse_args(argv)
    main = load_main()
    try:
        res = resegment(main, a.project, a.file, a.apply, a.offline)
    except Refuse as e:
        print("Отказ: %s" % e, file=sys.stderr)
        return 1
    except Exception as e:                  # HTTPException приложения — тоже отказ
        detail = getattr(e, "detail", None)
        print("Отказ: %s" % (detail or e), file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    print("Проект %d, исходник %s (%s)" % (res["project"], res["file"], res["kind"]))
    print("  было сегментов: %d, станет единиц: %d" % (res["oldSegments"], res["newUnits"]))
    print("  без изменений (перевод и статус остаются): %d" % res["kept"])
    print("  изменились (перевод обнулён, прежний — в prevTarget): %d, из них с переводом: %d"
          % (res["changed"], res["changedFromTranslated"]))
    print("  новые: %d" % res["new"])
    print("  ушли без замены: %d, из них с переводом: %d" % (res["removed"], res["removedTranslated"]))
    print("  сегментов с картинок: %d" % res["images"])
    for s in res["samples"]:
        print("    было: %s" % " | ".join((x or "")[:90] for x in s["old"]))
        print("    стало: %s" % s["new"][:180])
    if res["dryRun"]:
        print("Сухой прогон: ничего не записано. Запись — с --apply.")
    else:
        print("Записано. Копия для отката: reimport-%s (кнопка отката замены файла). "
              "Сегментов с картинок оставлено: %d." % (res["stamp"], res["imagesKept"]))
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
