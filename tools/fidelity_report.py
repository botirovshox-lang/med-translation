"""Замеры точности по эталонным проектам-картинкам (`backend/fidelity.py`).

Перерисовывает картинки слайдов лендинга тем же путём, что выгрузка
(`tools/landing_photo.render`), и меряет каждую надпись против оригинала:
высота строчных, плотность, цвет, остаток оригинала, значки, рисунок вне
рамок. Ничего не пишет ни в базу, ни на диск; моделей не зовёт.

    bash tools/prod_run.sh tools/fidelity_report.py           # таблица
    bash tools/prod_run.sh tools/fidelity_report.py --json    # базовая линия

Код возврата 1 — есть предупреждения (годится для cron и сверки выкатов).
"""
import json
import sys
from pathlib import Path

APP = Path("/opt/med-translation")
sys.path.insert(0, str(APP / "backend"))
sys.path.insert(0, str(APP / "tools"))
import fidelity  # noqa: E402
import landing_photo as lp  # noqa: E402


def main():
    as_json = "--json" in sys.argv
    rows, warned = {}, 0
    for slide, langs in lp.SLIDES.items():
        for lang, pid in langs.items():
            orig, out, _rep, items = lp.render(pid)
            if out is None:
                rows["%s-%s" % (slide, lang)] = {"warn": ["not_painted"]}
                warned += 1
                if not as_json:
                    # Строка обязательна: выкат сверяет число предупреждений
                    # (`tools/auto_rules/guard.py fid`), и молча пропавший эталон
                    # иначе выглядел бы как «стало лучше».
                    print("%-10s %4s - outside=- warn=['not_painted']" % (slide, lang))
                continue
            r = fidelity.compare(orig, out, items)
            rows["%s-%s" % (slide, lang)] = {"pid": pid, "summary": r["summary"],
                                             "outside": r["outside"], "warn": r["warn"],
                                             "blocks": [{k: v for k, v in m.items() if k != "box"}
                                                        for m in r["blocks"]]}
            warned += bool(r["warn"])
            if not as_json:
                print("%-10s %4s %s outside=%s warn=%s" % (slide, lang, r["summary"], r["outside"], r["warn"]))
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1, sort_keys=True))
    return 1 if warned else 0


if __name__ == "__main__":
    sys.exit(main())
