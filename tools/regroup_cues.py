#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пересобрать реплики ВИДЕО-проекта в предложения (инвариант 38,
«Строка субтитров — фраза»).

Зачем. Видео, распознанное до этой правки, хранит реплики такими, какими их
отдало распознавание: кусками по дыханию («بالنسبة لي» / «اللغة العربية» /
«هي اللغة التي…»). Каждый кусок — отдельная строка, и переводился он
обособленно. Инструмент склеивает хранимые реплики в предложения тем же
правилом, что и новое распознавание (`media.sentence_cues`), и подаёт
получившийся .srt тем же путём, что `tools/resegment_project.py` («Заменить
файл» без списания страниц, `_resegment_apply`):
  * строка, которая не изменилась, остаётся целиком;
  * изменившаяся заводится заново (статус new), прежний перевод её кусков —
    в `prevTarget`, текст кусков — в `prevSource`;
  * копия и откат — как у замены файла (`/reimport/{stamp}/undo`);
  * опорные точки пауз (`cueSpans`) пишутся по времени прежних кусков —
    экранные части потом не повиснут в тишине.
Переводить заново надо по-настоящему — это вызовы модели (`--translate`
ставит задачу перевода непереведённых строк; делает её воркер).
`--render subs,dub` ставит сборки видео (дорожка субтитров, озвучка) —
после того, как перевод закончен.

Запуск (на сервере — с окружением сервиса):
    python3 tools/regroup_cues.py 12                   # сухой прогон: числа
    python3 tools/regroup_cues.py 12 --apply --translate
    python3 tools/regroup_cues.py 12 --render subs,dub --voice f1
Код возврата: 0 — готово, 1 — отказ с причиной.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resegment_project as rs  # noqa: E402

Refuse = rs.Refuse


# Сколько знаков в секунду произносит диктор — оценка, чтобы снять
# растяжку коротких кусков (см. `_untidy`).
SPEECH_CPS = 14.0


def _untidy(raw: list) -> list:
    """Хранимый .srt уже прошёл `tidy_cues`: короткий кусок растянут до
    секунды (или до «следующее начало − 0,04»), и паузы после него выглядят
    короче настоящих — склейка реже закрывала бы фразу, а экранная часть
    висела бы в тишине. Файлов распознавания со словами у старого проекта
    больше нет, поэтому конец такого куска ОЦЕНИВАЕТСЯ по длине текста.
    Кусок длиннее секунды не растягивался — его время настоящее."""
    out = []
    for c in raw:
        d = c["end"] - c["start"]
        if d <= 1.0 + 1e-6:
            est = max(0.3, len(c["text"]) / SPEECH_CPS)
            c = dict(c, end=round(c["start"] + min(d, est), 3))
        out.append(c)
    return out


def regroup_srt(main, text: str) -> tuple:
    """(новый .srt, единицы, сколько было кусков) — хранимые реплики → фразы."""
    media = main.media_mod
    raw = _untidy([{"start": c["start"], "end": c["end"], "text": c["text"]}
                   for c in main.importers.cue_list(text)
                   if c.get("start") is not None and (c.get("text") or "").strip()])
    units = media.tidy_cues(media.sentence_cues(raw))
    return main.importers.render_cues(units, ".srt"), units, len(raw)


def _fresh(main, pid: int) -> dict:
    if getattr(main.STORE, "kind", "") == "pg":
        key = "projects:%d" % pid
        main._apply_doc(key, main.STORE.load_doc(key))
    return rs.find_project(main, pid)


def _busy(main, pid: int):
    jid = main._active_job_for(pid)
    if not jid:
        jid = main.STORE.active_job_for(pid)
    return jid


def _need_worker(main) -> None:
    """Задачу исполняет medcat-worker из таблицы jobs. Без внешнего воркера
    `_job_enqueue` запустил бы её потоком САМОГО инструмента, а инструмент
    тут же выходит — задача осталась бы «идёт», и правки проекта отвечали
    бы 409."""
    if not getattr(main, "EXTERNAL_WORKER", False):
        raise Refuse("Нет внешнего воркера (MEDCAT_EXTERNAL_WORKER=1 и база): поставить задачу "
                     "из инструмента нельзя — запустите перевод или сборку кнопкой в приложении")


def regroup(main, pid: int, apply=False, translate=False) -> dict:
    if apply and getattr(main.STORE, "kind", "file") != "pg":
        raise Refuse("Запись — только с базой (DATABASE_URL): второй пишущий процесс рядом "
                     "с сервисом затёр бы state.json (инвариант 1)")
    if apply and translate:
        _need_worker(main)
    project = _fresh(main, pid)
    if not project.get("media"):
        raise Refuse("Проект %d — не видео: реплики загруженного .srt — нарезка клиента" % pid)
    orig = main._orig_existing(pid)
    if orig is None:
        raise Refuse("У проекта нет хранимых субтитров")
    text, _enc = main.textcount._decode(orig.read_bytes())
    srt, units, n_raw = regroup_srt(main, text)
    name = project.get("fileName") or "subs.srt"
    content = srt.encode("utf-8")
    parsed = main._resegment_parse(name, content)
    pl = main._resegment_plan(project, parsed)
    confirmed = sum(1 for s in project.get("segments") or [] if s.get("status") == "confirmed")
    out = {"project": pid, "was": n_raw, "units": len(units), "dryRun": not apply,
           "confirmedBefore": confirmed, **pl["counts"],
           "sample": [u["text"] for u in units[:8]]}
    if not apply:
        return out
    jid = _busy(main, pid)
    if jid:
        raise Refuse("По проекту идёт или ждёт прогон №%s — подождите его конца" % jid)
    kind = project.get("importKind")
    try:
        out.update(main._resegment_apply(pid, parsed, content, name, pl))
    except main.HTTPException as e:
        raise Refuse(str(e.detail))
    with main._SAVE_LOCK:
        project = main.get_project(pid)
        if kind:
            project["importKind"] = kind          # «видео», а не «srt»: так его видит экран
        main._media_store_spans(project, units)
        main.save_state(main.STATE)
    # Вторая запись — тоже новость для API: иначе он перечитал бы проект
    # по эпохе первой записи и жил бы без опорных точек и с importKind «srt».
    main.STORE.bump_epoch("doc:projects:%d" % pid)
    if translate:
        ids = [s["id"] for s in project.get("segments") or []
               if (s.get("origin") or {}).get("kind") != "image" and main._needs_translation(s)]
        if ids:
            job = main._job_enqueue(pid, "translate", ids, {"force": False})
            out["translateJob"] = job["id"]
            out["toTranslate"] = len(ids)
    return out


def render(main, pid: int, what: list, voice: str) -> dict:
    _need_worker(main)
    project = _fresh(main, pid)
    if not project.get("media"):
        raise Refuse("Проект %d — не видео" % pid)
    jid = _busy(main, pid)
    if jid:
        raise Refuse("По проекту идёт или ждёт прогон №%s — сборка подождёт" % jid)
    left = sum(1 for s in project.get("segments") or [] if main._needs_translation(s))
    if left:
        raise Refuse("Не переведено строк: %d — сначала перевод" % left)
    jobs = {}
    for w in what:
        params = {"what": w}
        if w == "dub":
            params["voice"] = main._media_voice(voice or "")["id"]
        jobs[w] = main._job_enqueue(pid, "mediarender", [], params)["id"]
    return {"project": pid, "jobs": jobs}


def main_cli(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Реплики видео-проекта → предложения")
    ap.add_argument("project", type=int)
    ap.add_argument("--apply", action="store_true", help="записать (по умолчанию — только числа)")
    ap.add_argument("--translate", action="store_true", help="после записи поставить перевод")
    ap.add_argument("--render", default="", help="поставить сборки: subs,dub")
    ap.add_argument("--voice", default="", help="голос озвучки (f1, m1…)")
    a = ap.parse_args(argv)
    main = rs.load_main()
    try:
        if a.render:
            res = render(main, a.project, [w for w in a.render.split(",") if w in ("subs", "dub")], a.voice)
        else:
            res = regroup(main, a.project, a.apply, a.translate)
    except Exception as e:
        print("Отказ: %s" % (getattr(e, "detail", None) or e), file=sys.stderr)
        return 1
    for k, v in res.items():
        print("%s: %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
