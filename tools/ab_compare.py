#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слепое сравнение двух переводов одного файла: «было» против «стало».

Зачем. Правка промпта перевода (свой предыдущий перевод как обстановка,
справка о документе, ревизия со стыками — «лучше чата») обещает связность,
а связность никакой счётчик системы не меряет: разнобой терминов ловит
termcheck, а местоимения, отсылки и «один оборот двумя словами подряд» —
никто. Оценка ревизии после правки меряет уже ИЗМЕНЁННЫМ судьёй, то есть
сравнение «до/после» по ней смешано. Честная мера одна — человек, который
знает оба языка, читает две версии вслепую.

Как. Один и тот же файл загружается двумя проектами (A — прежний порядок,
например с TRANSLATE_PREV_CTX=0; B — новый) и переводится. Этот скрипт:
  • берёт сегменты обоих проектов (только чтение, ни одного вызова модели);
  • сопоставляет строки по ОРИГИНАЛУ, берёт подряд идущий кусок (по умолчанию
    40 строк — связность видна только подряд) и для каждой строки случайно
    решает, слева будет A или B;
  • пишет в backend/data/reports/ страницу: оригинал, два перевода, выбор
    «лучше слева / справа / одинаково»; кнопка «Итог» раскрывает, где был
    новый перевод, и считает победы;
  • печатает рядом бесплатные числа `/analysis` обоих проектов (готовность,
    корзины) — довод, а не приговор.

Запуск:
    APP_PASSWORD=... python3 tools/ab_compare.py -a 12 -b 13 [--start 100] [--n 40]
"""
import argparse
import base64
import html
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from after_run import REPORT_DIR, Fail, call, login  # noqa: E402


def segments(token, pid):
    p = call("GET", "/api/projects/%d" % pid, token)
    p = p.get("project", p)
    return p.get("title") or ("#%d" % pid), [s for s in p.get("segments") or []
                                              if (s.get("source") or "").strip()]


def pair_rows(sa, sb, start, n):
    """Строки обоих проектов с ОДИНАКОВЫМ оригиналом, подряд, в порядке A."""
    by_src = {}
    for s in sb:
        by_src.setdefault(" ".join(s["source"].split()), []).append(s)
    rows = []
    for s in sa[start:]:
        key = " ".join(s["source"].split())
        twins = by_src.get(key) or []
        if not twins:
            continue
        t = twins.pop(0)
        ta, tb = (s.get("target") or "").strip(), (t.get("target") or "").strip()
        if not ta or not tb:
            continue
        rows.append({"src": s["source"].strip(), "a": ta, "b": tb, "same": ta == tb})
        if len(rows) >= n:
            break
    return rows


def page(title_a, title_b, rows, seed):
    rnd = random.Random(seed)
    key, body = [], []
    for i, r in enumerate(rows):
        left_is_b = rnd.random() < 0.5
        key.append(1 if left_is_b else 0)
        left, right = (r["b"], r["a"]) if left_is_b else (r["a"], r["b"])
        body.append(
            '<tr><td class="n">%d</td><td>%s</td><td>%s</td><td>%s</td><td class="c">%s</td></tr>'
            % (i + 1, html.escape(r["src"]), html.escape(left), html.escape(right),
               "одинаково" if r["same"] else
               "".join('<label><input type="radio" name="r%d" value="%s">%s</label>'
                       % (i, v, t) for v, t in (("L", "слева"), ("R", "справа"), ("E", "равно")))))
    k = base64.b64encode(json.dumps(key).encode()).decode()
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Слепое сравнение</title>
<style>body{font:15px/1.45 system-ui,sans-serif;margin:16px;color:#222;background:#fff}
table{border-collapse:collapse;width:100%%}td,th{border:1px solid #ddd;padding:6px;vertical-align:top}
td.n{color:#999;width:2em}td.c{white-space:nowrap}label{display:block}
#out{margin:16px 0;font-weight:600}</style></head><body>
<h1>Слепое сравнение переводов</h1>
<p>Читайте подряд: связность видна только в ряду. В каждой строке отметьте, какой
перевод лучше. Где новый вариант, скрыто до кнопки «Итог».</p>
<table><tr><th>#</th><th>Оригинал</th><th>Слева</th><th>Справа</th><th>Лучше</th></tr>%s</table>
<p><button onclick="res()">Итог</button></p><div id="out"></div>
<script>
var K=JSON.parse(atob("%s"));
function res(){var a=0,b=0,e=0,left=0;for(var i=0;i<K.length;i++){
var x=document.querySelector('input[name="r'+i+'"]:checked');if(!x){continue}
if(x.value==="E"){e++;continue}var bSide=K[i]?"L":"R";if(x.value===bSide)b++;else a++}
for(var j=0;j<K.length;j++){if(document.querySelector('input[name="r'+j+'"]')&&!document.querySelector('input[name="r'+j+'"]:checked'))left++}
document.getElementById("out").textContent="Лучше «%s»: "+a+" · лучше «%s»: "+b+" · равно: "+e+(left?" · не отмечено: "+left:"")}
</script></body></html>""" % ("\n".join(body), k, html.escape(title_a), html.escape(title_b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-a", type=int, required=True, help="проект «было»")
    ap.add_argument("-b", type=int, required=True, help="проект «стало»")
    ap.add_argument("--start", type=int, default=0, help="с какой строки проекта A")
    ap.add_argument("--n", type=int, default=40, help="сколько строк подряд")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    try:
        token = login()
        ta, sa = segments(token, args.a)
        tb, sb = segments(token, args.b)
        rows = pair_rows(sa, sb, args.start, args.n)
        if not rows:
            print("Общих переведённых строк нет — это точно один и тот же файл?")
            return 2
        seed = args.seed if args.seed is not None else random.randrange(1 << 30)
        os.makedirs(REPORT_DIR, exist_ok=True)
        out = os.path.join(REPORT_DIR, "ab-%d-%d.html" % (args.a, args.b))
        with open(out, "w", encoding="utf-8") as f:
            f.write(page(ta, tb, rows, seed))
        diff = sum(1 for r in rows if not r["same"])
        print("Страница: %s" % out)
        print("Строк: %d, различаются: %d" % (len(rows), diff))
        for pid, title in ((args.a, ta), (args.b, tb)):
            an = call("GET", "/api/projects/%d/analysis" % pid, token)
            tk = an.get("turnkey") or {}
            n = {k: len(tk.get(k) or []) for k in ("ready", "machine", "human")}
            print("%s: готово %d · доделает машина %d · спросит человека %d"
                  % (title, n["ready"], n["machine"], n["human"]))
    except Fail as e:
        print("Не удалось: %s" % e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
