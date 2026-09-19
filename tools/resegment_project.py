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
    в `prev_target` (и их текст — в `prev_source`), чтобы человек собрал
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
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from contextlib import contextmanager
from datetime import datetime
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


@contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


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


def plan_of(main, project: dict, parsed: dict) -> dict:
    """План пересборки: что остаётся, что меняется (и из каких старых
    сегментов), что новое, что уходит. Тот же диф, что у замены файла."""
    units, full = parsed["units"], parsed["full"]
    old = main._text_segments(project)
    plan, removed = main._diff_units(project, units, full)
    pos = {id(s): i for i, s in enumerate(old)}
    removed_ids = {id(s) for s in removed}
    # Старые позиции «якорей» (оставшихся на месте) слева и справа от каждой
    # новой единицы: окно старых сегментов между ними — кандидаты «того же места».
    keep_pos = [pos[id(p[1])] if p and p[0] == "keep" else None for p in plan]
    changed, new = {}, []
    used = set()
    for j, item in enumerate(plan):
        if not item or item[0] != "new":
            continue
        lo = next((keep_pos[k] for k in range(j - 1, -1, -1) if keep_pos[k] is not None), -1)
        hi = next((keep_pos[k] for k in range(j + 1, len(plan)) if keep_pos[k] is not None), len(old))
        w_new = _words(units[j][0])
        got = []
        for i in range(lo + 1, hi):
            s = old[i]
            if id(s) not in removed_ids:
                continue
            w_old = _words(s.get("source"))
            if w_new and w_old and len(w_new & w_old) >= PREV_OVERLAP * min(len(w_new), len(w_old)):
                got.append(s)
        if got:
            changed[j] = got
            used.update(id(s) for s in got)
        else:
            new.append(j)
    gone = [s for s in removed if id(s) not in used]
    counts = {"kept": sum(1 for p in plan if p and p[0] in ("keep", "moved")),
              "changed": len(changed), "new": len(new), "removed": len(gone),
              "removedTranslated": sum(1 for s in gone if (s.get("target") or "").strip()),
              "changedFromTranslated": sum(1 for j, ss in changed.items()
                                           if any((s.get("target") or "").strip() for s in ss)),
              "oldSegments": len(old), "newUnits": len(units),
              "images": len(main._image_segments(project))}
    return {"plan": plan, "removed": removed, "changed": changed, "new": new, "gone": gone,
            "counts": counts}


def _media(docx_bytes: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            return {n: hashlib.sha1(z.read(n)).hexdigest() for n in z.namelist()
                    if n.startswith("word/media/")}
    except Exception:
        return {}


def apply_plan(main, pid: int, parsed: dict, content: bytes, filename: str, pl: dict) -> dict:
    """Запись: замена файла без списания, `prev_target` у изменившихся,
    картинки на месте, если не изменились."""
    project = main.get_project(pid)
    main._guard_project_write(pid)
    jid = main._active_job_for(pid)
    if not jid:
        try:
            jid = main.STORE.active_job_for(pid)     # таблица задач базы (у файла — пусто)
        except Exception as e:
            raise Refuse("Не проверить, идёт ли прогон по проекту: %s" % e)
    if jid or main._job_busy(pid, "images"):
        raise Refuse("По проекту идёт или ждёт прогон №%s — пересборка подождёт его конца" % jid)
    keep_fields = {k: project.get(k) for k in ("pages", "pagesUnit")}
    docx_path, _map = main._source_paths(pid)
    old_docx = docx_path.read_bytes() if docx_path.exists() else b""
    images_same = bool(old_docx) and _media(old_docx) == _media(parsed["docx"])
    old_order = list(project.get("segments") or [])
    img_segs = [s for s in old_order if (s.get("origin") or {}).get("kind") == "image"]
    with patched(main, "_pages_debit", lambda *a, **k: 0.0), \
            patched(main, "_auto_read_images", lambda *a, **k: None):
        done = main._reimport_apply(pid, parsed, content, filename, "")
    project = main.get_project(pid)
    by_id = {s["id"]: s for s in project["segments"]}
    added = list(done.get("addedIds") or [])
    new_js = [j for j, p in enumerate(pl["plan"]) if p and p[0] == "new"]
    for j, sid in zip(new_js, added):
        olds = pl["changed"].get(j)
        seg = by_id.get(sid)
        if not olds or seg is None:
            continue
        tg = [s.get("target") for s in olds if (s.get("target") or "").strip()]
        if tg:
            seg["prev_target"] = "\n".join(tg)
        seg["prev_source"] = "\n".join(s.get("source") or "" for s in olds)
    restored = 0
    if img_segs and images_same:
        # Картинки те же — их сегменты и карта картинок (перенесена
        # `_store_source_docx`) остаются в силе: ставим каждый за тот
        # текстовый сегмент, за которым он стоял, если тот уцелел.
        segs = project["segments"]
        live = {s["id"] for s in segs}
        prev_text = None
        anchor_of = {}
        for s in old_order:
            if (s.get("origin") or {}).get("kind") == "image":
                anchor_of[s["id"]] = prev_text
            else:
                prev_text = s["id"] if s["id"] in live else prev_text
        last = {}
        for s in img_segs:
            if s["id"] in live:
                continue
            a = anchor_of.get(s["id"])
            if a is None and last.get(None) is None:
                segs.insert(0, s)                    # картинка в самом начале документа
            else:
                main._image_place_segment(project, s, a, last.get(a))
            last[a] = s["id"]
            live.add(s["id"])
            restored += 1
        if project.get("reimport"):
            project["reimport"]["images"] = 0
    project.update(keep_fields)
    project["resegment"] = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "stamp": done.get("stamp"), **pl["counts"],
                            "imagesKept": restored}
    main._PROJECTS_VER[0] += 1
    main.save_state(main.STATE)
    if getattr(main.STORE, "kind", "") == "pg":
        main.STORE.bump_epoch("doc:projects:%d" % pid)   # API перечитает проект
    main._audit("project.resegment", project=pid, stamp=done.get("stamp"),
                changed=pl["counts"]["changed"], added=pl["counts"]["new"],
                removed=pl["counts"]["removed"], kept=pl["counts"]["kept"])
    return {"stamp": done.get("stamp"), "imagesKept": restored,
            "imagesRemoved": 0 if restored else done.get("imagesRemoved", 0)}


def resegment(main, pid: int, file_arg=None, apply=False, offline=False) -> dict:
    """Весь путь инструмента; бросает `Refuse` с причиной."""
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
    # Разбор того же файла мог остаться в кэше приложения со старыми
    # правилами — пересобираем заново.
    with main._PARSE_LOCK:
        main._PARSE_CACHE.pop((hashlib.sha1(content).hexdigest(), main.importers.ext_of(filename)), None)
    try:
        parsed = main._parse_upload(filename, content)
    except Exception as e:
        raise Refuse("Исходник не разобрался (%s): %s" % (where, e))
    if not parsed["units"]:
        raise Refuse("В исходнике не нашлось ни одной строки текста — пересобирать нечего")
    pl = plan_of(main, project, parsed)
    out = {"project": pid, "file": where, "kind": parsed["kind"], "dryRun": not apply,
           **pl["counts"],
           "samples": [{"old": [s.get("source") for s in pl["changed"][j]][:3],
                        "new": parsed["units"][j][0]} for j in list(pl["changed"])[:5]],
           "removedSample": [s.get("source") for s in pl["gone"][:5]]}
    if apply:
        out.update(apply_plan(main, pid, parsed, content, filename, pl))
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
    print("  изменились (перевод обнулён, прежний — в prev_target): %d, из них с переводом: %d"
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
