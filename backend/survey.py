# -*- coding: utf-8 -*-
"""Публичные страницы тест-группы: два опроса, инструкция и лист с ответами.

ПОЧЕМУ ЭТО ЖИВЁТ У НАС, А НЕ АРТЕФАКТОМ. Опросы начинались страницами
claude.ai: они умеют показать вопросы, но не умеют ОТПРАВИТЬ ответ — правила
безопасности артефакта запрещают запрос на чужой хост. Поэтому единственным
способом доставки было «скопируйте текст и пришлите в Telegram», а чтобы
человеку было куда слать, в странице стоял НИК владельца. Ник — не служебная
деталь: по нему пишут в личку кому угодно, и просьба его не публиковать
законна.

Отсюда всё устройство модуля:
  * страницы отдаёт наш сервер (`/t/...`) — значит, ответ уходит на наш же
    `/api/public/survey`, а оттуда ботом владельцу по ЧИСЛОВОМУ id;
  * ника нет ни в разметке, ни в тексте — доставку делает бот;
  * у каждого заполнения свой лист (`/t/a/{token}`): в Telegram уходит
    короткий текст и ссылка на полный лист с отмеченными вариантами.

Вопросы лежат ЗДЕСЬ, а не в разметке, и это несущее свойство: по одному
и тому же дереву рисуется страница (браузером), собирается текст для Telegram
и рисуется лист ответов (сервером). Разойдись они — владелец читал бы одни
формулировки, а отвечавший видел другие.

Язык — второй закон модуля. Сервис продаётся в Узбекистане, поэтому у каждой
строки два варианта, и выбранный язык ЕДЕТ ВМЕСТЕ С ОТВЕТОМ: лист ответов
показывает человеку то, что он читал, а не перевод.
"""

import html
import json

VERSION = "1"
BRAND = "SimpleTranslate"
LANGS = ("ru", "uz")


def _lang(v: str) -> str:
    """Язык страницы. Неизвестный код — узбекский: сервис продаётся
    в Узбекистане, и по умолчанию разговариваем на языке рынка."""
    v = (v or "").strip().lower()[:2]
    return v if v in LANGS else "uz"


# ─────────────────────────────────────────────────────────────────────
# Оформление. Одно на все четыре страницы: опрос набора, опрос разбора,
# инструкция и лист ответов — они должны выглядеть одной серией.
# ─────────────────────────────────────────────────────────────────────
CSS = r"""
:root{
  color-scheme:dark;
  --ground:#1A1B1E; --panel:#232529; --panel-2:#2A2D32;
  --ink:#F4F1EA; --muted:#9AA3AD; --stroke:#3C4046;
  --mint:#7BE3B3; --mint-ink:#0F241C; --mint-soft:rgba(123,227,179,.13);
  --teal:#5FD2C8; --violet:#AD93F7; --tan:#E4A56E; --flag:#F2807F;
  --hand:"Shantell Sans","Comic Sans MS",cursive;
  --body:"Nunito","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --r-card:22px 8px 20px 10px/10px 20px 8px 22px;
  --r-card2:10px 22px 8px 20px/20px 10px 22px 8px;
  --r-chip:12px 20px 11px 18px/18px 11px 20px 12px;
  --r-pill:16px 24px 15px 22px/22px 15px 24px 16px;
  --sq-rule:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='12' viewBox='0 0 120 12'><path d='M0 6 C 10 2 20 10 30 6 S 50 2 60 6 S 80 10 90 6 S 110 2 120 6' fill='none' stroke='%233C4046' stroke-width='2.4' stroke-linecap='round'/></svg>");
  --sq-mint:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='12' viewBox='0 0 120 12'><path d='M0 6 C 10 2 20 10 30 6 S 50 2 60 6 S 80 10 90 6 S 110 2 120 6' fill='none' stroke='%237BE3B3' stroke-width='2.6' stroke-linecap='round'/></svg>");
}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--body);
  font-size:16.5px;line-height:1.6;-webkit-font-smoothing:antialiased;margin:0}
:focus-visible{outline:2px dashed var(--mint);outline-offset:3px}

.top{position:sticky;top:0;z-index:20;background:var(--ground)}
.top-in{max-width:760px;margin:0 auto;padding:13px 20px;display:flex;
  align-items:center;justify-content:space-between;gap:14px}
.brand{font-family:var(--hand);font-weight:700;font-size:17px;color:var(--ink);
  display:flex;align-items:baseline;gap:8px;min-width:0}
.brand span{font-family:var(--body);font-weight:600;font-size:12.5px;color:var(--muted);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.right{display:flex;align-items:center;gap:13px;flex:none}
.count{font-family:var(--hand);font-weight:600;font-size:15px;color:var(--muted);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.count b{color:var(--mint);font-weight:700}
.seg{display:inline-flex;border:2px solid var(--stroke);border-radius:var(--r-pill);
  overflow:hidden;background:var(--panel);flex:none}
.seg a,.seg button{appearance:none;background:none;border:0;padding:5px 15px;cursor:pointer;
  color:var(--muted);font-family:var(--hand);font-weight:600;font-size:15px;
  text-decoration:none;display:inline-block}
.seg a+a,.seg button+button{border-left:2px solid var(--stroke)}
.seg [aria-pressed="true"]{background:var(--mint);color:var(--mint-ink)}
.bar{height:12px;background:var(--sq-rule) repeat-x 0 50%}
.bar i{display:block;height:12px;width:0;background:var(--sq-mint) repeat-x 0 50%;
  transition:width .4s cubic-bezier(.2,.7,.3,1)}

.wrap{max-width:760px;margin:0 auto;padding:0 20px 80px}
main{display:flex;flex-direction:column;gap:14px}

.lede{padding:40px 0 22px}
.lede .eyebrow{display:inline-block;font-family:var(--hand);font-weight:600;font-size:14px;
  color:var(--tan);border:2px solid var(--tan);border-radius:var(--r-chip);
  padding:4px 13px;margin:0 0 20px;transform:rotate(-1deg)}
h1{font-family:var(--hand);font-weight:700;font-size:clamp(30px,5.4vw,45px);line-height:1.14;
  margin:0 0 16px;text-wrap:balance;color:var(--ink)}
.lede p{margin:0 0 22px;color:var(--muted);max-width:60ch}
.facts{display:flex;flex-wrap:wrap;gap:9px;margin:0;padding:0;list-style:none}
.facts li{font-family:var(--hand);font-weight:500;font-size:14.5px;color:var(--muted);
  border:2px solid var(--stroke);border-radius:var(--r-chip);padding:4px 13px;background:var(--panel)}
.facts li:nth-child(1){color:var(--teal);border-color:var(--teal);transform:rotate(-.7deg)}
.facts li:nth-child(2){color:var(--violet);border-color:var(--violet);transform:rotate(.6deg)}
.facts li:nth-child(3){color:var(--tan);border-color:var(--tan);transform:rotate(-.4deg)}

.who{display:flex;flex-wrap:wrap;gap:14px 20px;align-items:flex-end;padding:20px 24px;
  background:var(--panel);border:2px dashed var(--stroke);border-radius:var(--r-card2)}
.who .fld{flex:1 1 240px}
.who .hint{flex:1 1 220px}
.who.miss{border-color:var(--flag)}

.q{display:grid;grid-template-columns:44px 1fr;gap:0 16px;align-items:start;
  background:var(--panel);border:2px solid var(--stroke);border-radius:var(--r-card);
  padding:22px 24px}
.q:nth-of-type(even){border-radius:var(--r-card2)}
.q.miss{border-color:var(--flag)}
.q-n{padding-top:2px}
.q-n b{display:grid;place-items:center;width:32px;height:32px;font-family:var(--hand);
  font-weight:600;font-size:15px;color:var(--c);border:2px solid var(--c);
  border-radius:58% 42% 55% 45%/48% 58% 42% 52%}
.c0{--c:var(--mint)} .c1{--c:var(--teal)} .c2{--c:var(--violet)} .c3{--c:var(--tan)}
.q.miss .q-n b{--c:var(--flag)}
.q-h{font-family:var(--hand);font-size:21px;font-weight:600;line-height:1.32;
  margin:0 0 5px;text-wrap:balance}
.q-sub{color:var(--muted);font-size:14.5px;margin:0;max-width:58ch;line-height:1.5}
.q-body{margin-top:15px}

.opts{display:flex;flex-wrap:wrap;gap:9px}
.opt{position:relative;display:inline-flex;align-items:center;gap:9px;cursor:pointer;
  border:2px solid var(--stroke);background:var(--panel-2);border-radius:var(--r-chip);
  padding:8px 15px;font-size:15px;line-height:1.3;color:var(--ink);
  transition:border-color .15s,background .15s}
.opt:hover{border-color:var(--mint)}
.opt input{position:absolute;opacity:0;width:1px;height:1px;margin:0}
.opt .tick{width:17px;height:17px;flex:none;border:2px solid var(--stroke);
  border-radius:58% 42% 55% 45%/48% 58% 42% 52%;display:grid;place-items:center;
  transition:border-color .15s}
.opt.box .tick{border-radius:6px 3px 7px 4px/4px 7px 3px 6px}
.opt .tick::after{content:"";width:8px;height:8px;border-radius:inherit;
  background:transparent;transition:background .15s}
.opt:has(input:checked){border-color:var(--mint);background:var(--mint-soft)}
.opt:has(input:checked) .tick{border-color:var(--mint)}
.opt:has(input:checked) .tick::after{background:var(--mint)}
.opt:has(input:focus-visible){outline:2px dashed var(--mint);outline-offset:3px}
.opt.on{border-color:var(--mint);background:var(--mint-soft)}
.opt.on .tick{border-color:var(--mint)}
.opt.on .tick::after{background:var(--mint)}
.opt.off{opacity:.62}

.scale{display:flex;flex-direction:column;gap:11px}
.scale-row{display:flex;gap:7px}
.scale-row .opt{flex:1 1 0;min-width:0;justify-content:center;padding:11px 0;
  font-family:var(--hand);font-weight:600;font-size:17px}
.scale-row .opt .tick{display:none}
.ends{display:flex;justify-content:space-between;gap:16px;font-size:13.5px;color:var(--muted)}
.ends span{max-width:46%}
.ends span:last-child{text-align:right}

.sub-label{font-family:var(--body);font-weight:700;font-size:11.5px;letter-spacing:.13em;
  text-transform:uppercase;color:var(--muted);margin:0 0 9px}
.gap{height:20px}
.fields{display:flex;flex-wrap:wrap;gap:18px}
.fld{flex:1 1 220px;min-width:0}
.fld label{display:block;font-family:var(--body);font-weight:700;font-size:11.5px;
  letter-spacing:.13em;text-transform:uppercase;color:var(--muted);margin:0 0 6px}
input[type=text]{width:100%;font-family:var(--body);font-size:16px;color:var(--ink);
  background:transparent;border:0;border-bottom:2.5px solid var(--stroke);padding:7px 3px;
  border-radius:0 0 40% 30%/0 0 10px 9px;transition:border-color .15s}
textarea{width:100%;font-family:var(--body);font-size:16px;color:var(--ink);
  background:var(--panel-2);border:2px solid var(--stroke);border-radius:var(--r-card);
  padding:12px 14px;resize:vertical;min-height:88px;line-height:1.55;transition:border-color .15s}
input[type=text]::placeholder,textarea::placeholder{color:#6B7480}
input[type=text]:focus{outline:0;border-bottom-color:var(--mint)}
textarea:focus{outline:0;border-color:var(--mint)}
.who.miss input[type=text]{border-bottom-color:var(--flag)}
.q.miss input[type=text]{border-bottom-color:var(--flag)}
.q.miss textarea{border-color:var(--flag)}
.answer{white-space:pre-wrap;font-size:15.5px;color:var(--ink);background:var(--panel-2);
  border:2px solid var(--stroke);border-radius:var(--r-card);padding:12px 14px;margin:0}
.answer.empty{color:var(--muted);font-style:italic}
.pair{font-size:15.5px;margin:0}
.pair b{color:var(--mint);font-weight:700}

.consent{display:flex;flex-direction:column;gap:14px;padding:22px 24px;
  background:var(--panel);border:2px dashed var(--stroke);border-radius:var(--r-card2)}
.chk{position:relative;display:flex;gap:12px;align-items:flex-start;cursor:pointer;
  font-size:15px;color:var(--muted);line-height:1.5;max-width:62ch}
.chk input{position:absolute;opacity:0;width:1px;height:1px}
.chk .tick{width:19px;height:19px;flex:none;margin-top:3px;border:2px solid var(--stroke);
  border-radius:6px 3px 7px 4px/4px 7px 3px 6px;display:grid;place-items:center}
.chk .tick::after{content:"";width:9px;height:9px;border-radius:inherit;background:transparent}
.chk:has(input:checked) .tick{border-color:var(--mint)}
.chk:has(input:checked) .tick::after{background:var(--mint)}
.chk:has(input:checked){color:var(--ink)}
.chk.on .tick{border-color:var(--mint)}
.chk.on .tick::after{background:var(--mint)}
.chk.on{color:var(--ink)}
.chk.miss{color:var(--flag)}
.chk.miss .tick{border-color:var(--flag)}
.chk:has(input:focus-visible) .tick{outline:2px dashed var(--mint);outline-offset:3px}

.send{margin-top:14px;display:flex;flex-direction:column;gap:16px;align-items:flex-start}
.btn{position:relative;font-family:var(--hand);font-weight:700;font-size:18px;
  border:2px solid var(--mint);background:var(--mint);color:var(--mint-ink);
  border-radius:var(--r-pill);padding:12px 28px;cursor:pointer;text-decoration:none;
  display:inline-block;transition:transform .12s,filter .12s}
.btn::after{content:"";position:absolute;inset:-7px;border:2px solid var(--mint);
  opacity:.38;border-radius:var(--r-card);transform:rotate(-1deg);pointer-events:none}
.btn:hover{transform:translate(-1px,-1px);filter:brightness(1.07)}
.btn:active{transform:translate(1px,1px)}
.btn[disabled]{opacity:.55;cursor:default;transform:none;filter:none}
.btn.ghost{background:transparent;border-color:var(--stroke);color:var(--ink);
  font-size:16px;padding:10px 20px}
.btn.ghost::after{border-color:var(--stroke);opacity:.32}
.btn.ghost:hover{border-color:var(--mint);color:var(--mint)}
.hint{font-size:14px;color:var(--muted);margin:0}
.hint.warn{color:var(--flag);font-weight:700}

.done{padding:44px 0 20px}
.stamp{display:inline-flex;align-items:center;gap:9px;font-family:var(--hand);font-weight:700;
  font-size:15px;color:var(--mint);background:var(--mint-soft);border:2px solid var(--mint);
  border-radius:var(--r-pill);padding:6px 17px;margin:0 0 22px;transform:rotate(-2deg)}
.done h2{font-family:var(--hand);font-size:32px;margin:0 0 14px;font-weight:700;text-wrap:balance}
.done p{color:var(--muted);margin:0 0 22px;max-width:58ch}
.row{display:flex;flex-wrap:wrap;gap:20px;margin-top:24px;align-items:center}

.step{display:grid;grid-template-columns:44px 1fr;gap:0 16px;align-items:start;
  background:var(--panel);border:2px solid var(--stroke);border-radius:var(--r-card);
  padding:22px 24px}
.step:nth-of-type(even){border-radius:var(--r-card2)}
.step h2{font-family:var(--hand);font-size:21px;font-weight:600;line-height:1.32;margin:0 0 6px}
.step p{margin:0 0 8px;color:var(--muted);font-size:15.5px;max-width:60ch}
.step p:last-child{margin-bottom:0}
.step b{color:var(--ink);font-weight:700}
.note{padding:20px 24px;background:var(--panel);border:2px dashed var(--stroke);
  border-radius:var(--r-card2);color:var(--muted);font-size:15px;margin:0}
.note b{color:var(--tan)}
.note+.note{margin-top:0}

@media (max-width:600px){
  .q,.step{grid-template-columns:1fr;gap:0;padding:20px 18px}
  .q-n{padding:0 0 10px}
  .scale-row{flex-wrap:wrap}
  .scale-row .opt{flex:1 1 46px}
  .top-in{padding:11px 16px}
  .wrap{padding:0 16px 64px}
  .lede{padding:32px 0 18px}
  .who,.consent{padding:18px}
  .count{display:none}
}
@media (prefers-reduced-motion:reduce){*{transition:none !important;scroll-behavior:auto !important}}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Nunito:wght@400;600;700&family=Shantell+Sans:wght@500;600;700&display=swap">')


# ═════════════════════════════════════════════════════════════════════
# ВОПРОСЫ. Одно дерево на три читателя: браузер рисует страницу, сервер
# собирает текст для Telegram и рисует лист ответов. Второго списка
# формулировок в системе быть не должно.
#
# Виды: one — один вариант; scale — шкала от..до; text — свободный текст;
#       fields — несколько строк ввода; group — несколько наборов галочек.
# ═════════════════════════════════════════════════════════════════════

APPLY = {
    "id": "apply",
    "path": "/t/apply",
    "T": {
        "ru": {
            "sub": "· набор тест-группы",
            "eyebrow": "Открытый набор",
            "h1": "Ищем переводчиков, которые сломают наш переводчик",
            "lede": "SimpleTranslate — CAT-система: переводит документ целиком, ведёт ваш "
                    "глоссарий, помнит прошлые переводы и возвращает готовый .docx в исходном "
                    "оформлении. Две недели работы на ваших настоящих текстах — и честный разбор "
                    "в конце. Бесплатно, по 20–30 страниц на человека.",
            "facts": ["7 вопросов", "около 3 минут", "ответы уходят напрямую разработчику"],
            "submit": "Отправить заявку",
            "sending": "Отправляем…",
            "miss": "Не хватает ответа в пункте ",
            "missChk": "Отметьте согласие внизу",
            "failed": "Не отправилось. Проверьте связь и нажмите ещё раз.",
            "done": "Заявка отправлена",
            "doneH": "Спасибо, мы её получили",
            "doneP": "Копировать и пересылать ничего не нужно — ответы уже у нас. Мы отвечаем "
                     "всем, кто заполнил, — и тем, кого не возьмём, тоже.",
            "mine": "Открыть мой лист ответов",
            "title": BRAND + " · заявка в тест-группу",
            "skip": "— (пропущено)",
        },
        "uz": {
            "sub": "· sinov guruhiga tanlov",
            "eyebrow": "Ochiq tanlov",
            "h1": "Tarjimonimizni sindiradigan tarjimonlar qidiryapmiz",
            "lede": "SimpleTranslate — CAT-tizim: hujjatni butunlay tarjima qiladi, lug'atingizni "
                    "yuritadi, oldingi tarjimalarni eslab qoladi va tayyor .docx faylni asl "
                    "bezagida qaytaradi. Ikki hafta o'z haqiqiy matnlaringiz ustida ish — va "
                    "oxirida halol tahlil. Bepul, har bir kishiga 20–30 sahifa.",
            "facts": ["7 ta savol", "taxminan 3 daqiqa", "javoblar to'g'ridan-to'g'ri ishlab chiquvchiga ketadi"],
            "submit": "Arizani yuborish",
            "sending": "Yuborilyapti…",
            "miss": "Javob yetishmayapti, band ",
            "missChk": "Quyidagi rozilikni belgilang",
            "failed": "Yuborilmadi. Aloqani tekshirib, yana bosing.",
            "done": "Ariza yuborildi",
            "doneH": "Rahmat, qabul qildik",
            "doneP": "Hech narsani nusxalab yuborish shart emas — javoblar bizda. To'ldirgan "
                     "hammaga javob beramiz, tanlanmaganlarga ham.",
            "mine": "Javoblar varag'imni ochish",
            "title": BRAND + " · sinov guruhiga ariza",
            "skip": "— (o'tkazib yuborildi)",
        },
    },
    "questions": [
        {"id": "contact", "type": "fields", "req": 1,
         "ru": {"q": "Как вас зовут и где вас найти?",
                "s": "Telegram нужен, чтобы выдать доступ и списаться."},
         "uz": {"q": "Ismingiz nima va sizni qayerdan topamiz?",
                "s": "Telegram kirish berish va bog'lanish uchun kerak."},
         "fields": [{"k": "name", "ru": "Имя и фамилия", "uz": "Ism va familiya", "ph": ""},
                    {"k": "tg", "ru": "Telegram", "uz": "Telegram", "ph": "@username"}]},

        {"id": "work", "type": "group", "req": 1,
         "ru": {"q": "Что вы переводите?", "s": "Отметьте всё, что про вас."},
         "uz": {"q": "Nimalarni tarjima qilasiz?", "s": "O'zingizga tegishli hammasini belgilang."},
         "parts": [
             {"k": "pairs", "ru": "Языковые пары", "uz": "Til juftliklari", "req": 1,
              "opts": [{"v": "RU-UZ", "ru": "RU → UZ"}, {"v": "UZ-RU", "ru": "UZ → RU"},
                       {"v": "RU-EN", "ru": "RU → EN"}, {"v": "EN-RU", "ru": "EN → RU"},
                       {"v": "UZ-EN", "ru": "UZ → EN"}, {"v": "EN-UZ", "ru": "EN → UZ"},
                       {"v": "other", "ru": "другие", "uz": "boshqalar"}]},
             {"k": "topics", "ru": "Темы", "uz": "Mavzular", "req": 1,
              "opts": [{"v": "med", "ru": "Медицина", "uz": "Tibbiyot"},
                       {"v": "law", "ru": "Договоры и юр. документы",
                        "uz": "Shartnoma va yuridik hujjatlar"},
                       {"v": "tech", "ru": "Техника и IT", "uz": "Texnika va IT"},
                       {"v": "fin", "ru": "Финансы и отчётность", "uz": "Moliya va hisobot"},
                       {"v": "docs", "ru": "Личные и официальные документы",
                        "uz": "Shaxsiy va rasmiy hujjatlar"},
                       {"v": "lit", "ru": "Художественный", "uz": "Badiiy"},
                       {"v": "other", "ru": "Другое", "uz": "Boshqa"}]}]},

        {"id": "years", "type": "one", "req": 1,
         "ru": {"q": "Сколько лет вы переводите?"},
         "uz": {"q": "Necha yildan beri tarjima qilasiz?"},
         "opts": [{"v": "lt1", "ru": "меньше года", "uz": "bir yildan kam"},
                  {"v": "1-3", "ru": "1–3 года", "uz": "1–3 yil"},
                  {"v": "3-7", "ru": "3–7 лет", "uz": "3–7 yil"},
                  {"v": "gt7", "ru": "больше 7 лет", "uz": "7 yildan ko'p"}]},

        {"id": "cat", "type": "one", "req": 1,
         "ru": {"q": "Работали в CAT-программах?",
                "s": "Trados, memoQ, Smartcat, Phrase — те, где текст разбит на сегменты, "
                     "а рядом глоссарий и память переводов."},
         "uz": {"q": "CAT-dasturlarda ishlaganmisiz?",
                "s": "Trados, memoQ, Smartcat, Phrase — matn segmentlarga bo'lingan, yonida "
                     "lug'at va tarjima xotirasi turadigan dasturlar."},
         "opts": [{"v": "daily", "ru": "Да, работаю в них постоянно", "uz": "Ha, doimiy ishlayman"},
                  {"v": "tried", "ru": "Пробовал(а), но не прижилось",
                   "uz": "Sinab ko'rganman, lekin ishlatmayman"},
                  {"v": "word", "ru": "Нет, перевожу в Word", "uz": "Yo'q, Word'da tarjima qilaman"},
                  {"v": "none", "ru": "Впервые слышу", "uz": "Birinchi marta eshityapman"}]},

        {"id": "doc", "type": "one", "req": 1,
         "ru": {"q": "Есть настоящий документ на 20–30 страниц, который и так надо перевести?",
                "s": "Страница — 250 слов. Тест на своём тексте показывает в разы больше, "
                     "чем на учебном."},
         "uz": {"q": "Shundoq ham tarjima qilish kerak bo'lgan 20–30 sahifalik haqiqiy hujjat bormi?",
                "s": "Sahifa — 250 so'z. O'z matningizda sinov o'quv matnidan ko'ra ancha ko'p "
                     "narsani ko'rsatadi."},
         "opts": [{"v": "yes", "ru": "Да, принесу свой", "uz": "Ha, o'zimnikini olib kelaman"},
                  {"v": "nda", "ru": "Есть, но он конфиденциальный", "uz": "Bor, lekin u maxfiy"},
                  {"v": "any", "ru": "Нет, возьму любой текст для теста",
                   "uz": "Yo'q, sinov uchun istalgan matnni olaman"}]},

        {"id": "hours", "type": "one", "req": 1,
         "ru": {"q": "Сколько часов за две недели реально сможете уделить?",
                "s": "Честный ответ полезнее красивого: мы считаем нагрузку, а не проверяем вас."},
         "uz": {"q": "Ikki hafta ichida rostdan necha soat ajrata olasiz?",
                "s": "Halol javob chiroylisidan foydaliroq: biz yukni hisoblaymiz, sizni "
                     "tekshirmaymiz."},
         "opts": [{"v": "lt2", "ru": "до 2 часов", "uz": "2 soatgacha"},
                  {"v": "3-5", "ru": "3–5 часов", "uz": "3–5 soat"},
                  {"v": "6-10", "ru": "6–10 часов", "uz": "6–10 soat"},
                  {"v": "gt10", "ru": "больше 10 часов", "uz": "10 soatdan ko'p"}]},

        {"id": "pain", "type": "text", "req": 1,
         "ru": {"q": "Что в вашей работе с переводом бесит больше всего?",
                "s": "Одна-две фразы. Это самый полезный вопрос анкеты — по нему мы и выбираем.",
                "ph": "Например: заказчик присылает PDF, и вёрстку приходится собирать заново вручную…"},
         "uz": {"q": "Tarjima ishingizda eng ko'p nima jahlingizni chiqaradi?",
                "s": "Bir-ikki jumla. Bu anketadagi eng foydali savol — biz aynan shunga qarab tanlaymiz.",
                "ph": "Masalan: buyurtmachi PDF yuboradi, bezakni esa qo'lda qaytadan yig'ishga to'g'ri keladi…"}},
    ],
    "consent": [
        {"k": "call", "req": 0,
         "ru": "Готов(а) в конце теста созвониться на 15 минут",
         "uz": "Sinov oxirida 15 daqiqa gaplashishga tayyorman"},
        {"k": "data", "req": 1,
         "ru": "Понимаю, что текст документа уходит на обработку поставщику языковых моделей "
               "(OpenAI, США), и не буду загружать то, что нельзя туда отправлять",
         "uz": "Hujjat matni til modellari yetkazib beruvchisiga (OpenAI, AQSh) qayta ishlashga "
               "ketishini tushunaman va u yerga yuborib bo'lmaydigan narsani yuklamayman"},
    ],
}

DEBRIEF = {
    "id": "debrief",
    "path": "/t/debrief",
    "T": {
        "ru": {
            "sub": "· разбор после теста",
            "eyebrow": "Финал теста · две недели позади",
            "h1": "Скажите честно, где мы вас подвели",
            "lede": "Вы дошли до конца — спасибо. Дальше 15 вопросов: почти везде достаточно "
                    "ткнуть в один вариант, писать руками надо в трёх. Хвалить не обязательно, "
                    "ругаться — можно и нужно: именно по этим ответам мы решаем, что чинить первым.",
            "facts": ["15 вопросов", "5–7 минут", "три вопроса со свободным текстом"],
            "whoLabel": "Ваш Telegram",
            "whoHint": "Чтобы понять, чей это разбор, и вернуться с вопросами.",
            "submit": "Отправить разбор",
            "sending": "Отправляем…",
            "miss": "Не хватает ответа в пункте ",
            "missWho": "Впишите свой Telegram вверху",
            "failed": "Не отправилось. Проверьте связь и нажмите ещё раз.",
            "done": "Разбор отправлен",
            "doneH": "Спасибо, мы его получили",
            "doneP": "Копировать и пересылать ничего не нужно — ответы уже у нас. Всё, что вы "
                     "написали, мы разберём поимённо — и вернёмся с тем, что из этого починили.",
            "mine": "Открыть мой лист ответов",
            "title": BRAND + " · разбор после теста",
            "skip": "— (пропущено)",
        },
        "uz": {
            "sub": "· sinovdan keyingi tahlil",
            "eyebrow": "Sinov yakuni · ikki hafta ortda qoldi",
            "h1": "Qayerda sizni ovora qilganimizni halol ayting",
            "lede": "Oxirigacha yetdingiz — rahmat. Endi 15 ta savol: deyarli hamma joyda bitta "
                    "variantni bosish kifoya, faqat uchtasida yozish kerak. Maqtash shart emas, "
                    "tanqid qilish — mumkin va kerak: aynan shu javoblarga qarab nimani birinchi "
                    "tuzatishni hal qilamiz.",
            "facts": ["15 ta savol", "5–7 daqiqa", "uchta savolda erkin matn"],
            "whoLabel": "Telegramingiz",
            "whoHint": "Bu kimning tahlili ekanini bilish va savol bilan qaytish uchun.",
            "submit": "Tahlilni yuborish",
            "sending": "Yuborilyapti…",
            "miss": "Javob yetishmayapti, band ",
            "missWho": "Yuqorida Telegramingizni yozing",
            "failed": "Yuborilmadi. Aloqani tekshirib, yana bosing.",
            "done": "Tahlil yuborildi",
            "doneH": "Rahmat, qabul qildik",
            "doneP": "Hech narsani nusxalab yuborish shart emas — javoblar bizda. Yozganingizning "
                     "hammasini birma-bir ko'rib chiqamiz — va nimani tuzatganimiz bilan qaytamiz.",
            "mine": "Javoblar varag'imni ochish",
            "title": BRAND + " · sinovdan keyingi tahlil",
            "skip": "— (o'tkazib yuborildi)",
        },
    },
    "who": {"id": "who", "type": "text"},
    "questions": [
        {"id": "overall", "type": "scale", "req": 1, "from": 1, "to": 5,
         "ru": {"q": "Как вообще прошло?", "lo": "мучение", "hi": "всё легко"},
         "uz": {"q": "Umuman olganda qanday o'tdi?", "lo": "azob", "hi": "hammasi oson"}},

        {"id": "import", "type": "one", "req": 1,
         "ru": {"q": "Файл загрузился нормально?", "s": "Речь про .docx, который вы приносили первым."},
         "uz": {"q": "Fayl normal yuklandimi?", "s": "Gap birinchi olib kelgan .docx faylingiz haqida."},
         "opts": [{"v": "ok", "ru": "Да, сразу", "uz": "Ha, darrov"},
                  {"v": "2nd", "ru": "Со второй-третьей попытки", "uz": "Ikkinchi-uchinchi urinishda"},
                  {"v": "fail", "ru": "Не загрузился — расскажу ниже", "uz": "Yuklanmadi — quyida aytaman"},
                  {"v": "no", "ru": "Не пробовал(а)", "uz": "Sinab ko'rmadim"}]},

        {"id": "quality", "type": "scale", "req": 1, "from": 1, "to": 5,
         "ru": {"q": "Качество перевода по вашей теме", "s": "Первый перевод, до ваших правок.",
                "lo": "переделывать всё", "hi": "почти не трогал(а)"},
         "uz": {"q": "O'z mavzuingiz bo'yicha tarjima sifati",
                "s": "Tuzatishlaringizgacha bo'lgan birinchi tarjima.",
                "lo": "hammasini qayta qilish kerak", "hi": "deyarli tegmadim"}},

        {"id": "export", "type": "one", "req": 1,
         "ru": {"q": "Экспорт «как в оригинале» — открывали файл в Word?",
                "s": "Заголовки, таблицы, картинки, колонтитулы: всё осталось на местах?"},
         "uz": {"q": "«Asl nusxadagidek» eksport — faylni Word'da ochdingizmi?",
                "s": "Sarlavhalar, jadvallar, rasmlar, kolontitullar: hammasi joyida qoldimi?"},
         "opts": [{"v": "ok", "ru": "Всё на месте", "uz": "Hammasi joyida"},
                  {"v": "minor", "ru": "Мелочи поехали", "uz": "Mayda narsalar surildi"},
                  {"v": "broken", "ru": "Оформление сломалось", "uz": "Bezak buzildi"},
                  {"v": "no", "ru": "Не экспортировал(а)", "uz": "Eksport qilmadim"}]},

        {"id": "gloss", "type": "one", "req": 1,
         "ru": {"q": "Глоссарий: разница между «приказом» и «подсказкой» понятна?",
                "s": "Приказ система обязана соблюсти, подсказку модель вправе проигнорировать."},
         "uz": {"q": "Lug'at: «buyruq» va «maslahat» farqi tushunarlimi?",
                "s": "Buyruqni tizim bajarishi shart, maslahatni model e'tiborsiz qoldirishi mumkin."},
         "opts": [{"v": "yes", "ru": "Понял(а) сразу", "uz": "Darrov tushundim"},
                  {"v": "late", "ru": "Дошло не сразу", "uz": "Darrov emas, keyinroq"},
                  {"v": "no", "ru": "Так и не понял(а)", "uz": "Oxirigacha tushunmadim"},
                  {"v": "skip", "ru": "Не заходил(а) в глоссарий", "uz": "Lug'atga kirmadim"}]},

        {"id": "terms", "type": "one", "req": 1,
         "ru": {"q": "Термины, которые система приносила на решение",
                "s": "Очередь кандидатов: одобрить, отклонить, поправить."},
         "uz": {"q": "Tizim yechim uchun keltirgan atamalar",
                "s": "Nomzodlar navbati: ma'qullash, rad etish, tuzatish."},
         "opts": [{"v": "liked", "ru": "Разбирал(а) с удовольствием", "uz": "Zavq bilan ko'rib chiqdim"},
                  {"v": "many", "ru": "Слишком много, забросил(а)", "uz": "Juda ko'p, tashlab qo'ydim"},
                  {"v": "unclear", "ru": "Не понял(а), чего от меня хотят",
                   "uz": "Mendan nima kutilayotganini tushunmadim"},
                  {"v": "skip", "ru": "Не дошёл(ла) до них", "uz": "Ularga yetib bormadim"}]},

        {"id": "analysis", "type": "one", "req": 1,
         "ru": {"q": "Экран «Анализ»: после прогона было ясно, что делать дальше?",
                "s": "Готово · Возьмёт прогон · Нужен человек."},
         "uz": {"q": "«Tahlil» ekrani: ishlovdan keyin nima qilish kerakligi aniq bo'ldimi?",
                "s": "Tayyor · Ishlov oladi · Odam kerak."},
         "opts": [{"v": "yes", "ru": "Да, шёл(шла) по строкам сверху вниз",
                   "uz": "Ha, qatorlar bo'yicha yurdim"},
                  {"v": "half", "ru": "Понятно наполовину", "uz": "Yarmi tushunarli"},
                  {"v": "no", "ru": "Смотрел(а) и не понимал(а)", "uz": "Qaradim-u tushunmadim"},
                  {"v": "skip", "ru": "Не открывал(а)", "uz": "Ochmadim"}]},

        {"id": "autofix", "type": "scale", "req": 1, "from": 1, "to": 5,
         "ru": {"q": "Система сама правит перевод — «Ремонт» и «Ревизия». Доверяете этим правкам?",
                "lo": "страшно, проверял(а) каждую", "hi": "доверяю, не проверял(а)"},
         "uz": {"q": "Tizim tarjimani o'zi tuzatadi — «Ta'mir» va «Reviziya». Bu tuzatishlarga ishonasizmi?",
                "lo": "qo'rqinchli, har birini tekshirdim", "hi": "ishonaman, tekshirmadim"}},

        {"id": "speed", "type": "one", "req": 1,
         "ru": {"q": "Скорость прогонов — терпимо?"},
         "uz": {"q": "Ishlov tezligi — chidasa bo'ladimi?"},
         "opts": [{"v": "fast", "ru": "Быстро", "uz": "Tez"},
                  {"v": "ok", "ru": "Терпимо", "uz": "Chidasa bo'ladi"},
                  {"v": "slow", "ru": "Долго, но дожидался(лась)", "uz": "Uzoq, lekin kutdim"},
                  {"v": "left", "ru": "Бросал(а) вкладку и уходил(а)", "uz": "Oynani tashlab ketardim"}]},

        {"id": "queue", "type": "one", "req": 1,
         "ru": {"q": "Ждали, пока освободится очередь прогонов?",
                "s": "Исполнитель один на всех, и задачи идут по кругу между участниками."},
         "uz": {"q": "Ishlovlar navbati bo'shashini kutdingizmi?",
                "s": "Ijrochi hammaga bitta, vazifalar ishtirokchilar orasida navbatma-navbat ketadi."},
         "opts": [{"v": "never", "ru": "Ни разу не заметил(а) очереди", "uz": "Navbatni sezmadim ham"},
                  {"v": "short", "ru": "Ждал(а), но недолго", "uz": "Kutdim, lekin uzoq emas"},
                  {"v": "long", "ru": "Ждал(а) долго", "uz": "Uzoq kutdim"},
                  {"v": "blocked", "ru": "Из-за очереди бросил(а) работу", "uz": "Navbat tufayli ishni tashladim"}]},

        {"id": "uz", "type": "text", "req": 0,
         "ru": {"q": "Узбекский интерфейс: где текст кривой или остался русским?",
                "s": "Не обязательно. Но если заметили — назовите экран или саму надпись.",
                "ph": "Например: на экране экспорта кнопка осталась по-русски…"},
         "uz": {"q": "O'zbekcha interfeys: matn qayerda g'aliz yoki ruscha qolgan?",
                "s": "Majburiy emas. Lekin sezgan bo'lsangiz — ekran nomini yoki yozuvning o'zini ayting.",
                "ph": "Masalan: eksport ekranida tugma ruscha qolgan…"}},

        {"id": "saved", "type": "one", "req": 1,
         "ru": {"q": "Сколько времени это сэкономило против вашего обычного способа?"},
         "uz": {"q": "Bu odatdagi usulingizga nisbatan qancha vaqt tejadi?"},
         "opts": [{"v": "worse", "ru": "Потратил(а) больше, чем обычно", "uz": "Odatdagidan ko'proq vaqt ketdi"},
                  {"v": "same", "ru": "Примерно столько же", "uz": "Taxminan bir xil"},
                  {"v": "third", "ru": "Сэкономило до трети", "uz": "Uchdan birgacha tejadi"},
                  {"v": "half", "ru": "Сэкономило половину и больше", "uz": "Yarmini va undan ko'pini tejadi"}]},

        {"id": "broke", "type": "text", "req": 1,
         "ru": {"q": "Что сломалось или бесило больше всего?",
                "s": "Хоть одним словом. Если было несколько — пишите списком, разберём всё.",
                "ph": "Например: после прогона таблица показывала старые статусы, пока не обновишь страницу…"},
         "uz": {"q": "Nima buzildi yoki eng ko'p jahlingizni chiqardi?",
                "s": "Bir og'iz so'z bilan bo'lsa ham. Bir nechta bo'lsa — ro'yxat qilib yozing, hammasini ko'ramiz.",
                "ph": "Masalan: ishlovdan keyin jadval eski holatlarni ko'rsatib turdi, sahifani yangilamaguncha…"}},

        {"id": "need", "type": "text", "req": 1,
         "ru": {"q": "Чего не хватает, чтобы пользоваться этим за деньги?",
                "s": "Одна вещь, без которой вы не купите. Самый дорогой для нас ответ.",
                "ph": "Например: без нечёткого поиска по памяти переводов я не откажусь от Trados…"},
         "uz": {"q": "Buni pulga ishlatish uchun nima yetishmayapti?",
                "s": "Sizsiz sotib olmaydigan bitta narsa. Biz uchun eng qimmatli javob.",
                "ph": "Masalan: tarjima xotirasida noaniq qidiruv bo'lmasa, Trados'dan voz kechmayman…"}},

        {"id": "price", "type": "one", "req": 1,
         "ru": {"q": "Если бы платили сами — сколько это стоит за страницу?",
                "s": "Страница — 250 слов исходника."},
         "uz": {"q": "O'zingiz to'laganingizda — bir sahifa qancha turadi?",
                "s": "Sahifa — asl matnning 250 so'zi."},
         "opts": [{"v": "0", "ru": "Не платил(а) бы", "uz": "To'lamagan bo'lardim"},
                  {"v": "0.5", "ru": "до $0.5", "uz": "$0.5 gacha"},
                  {"v": "1", "ru": "$0.5–1", "uz": "$0.5–1"},
                  {"v": "2", "ru": "$1–2", "uz": "$1–2"},
                  {"v": "3", "ru": "больше $2", "uz": "$2 dan ko'p"}]},

        {"id": "nps", "type": "scale", "req": 1, "from": 0, "to": 10,
         "ru": {"q": "Порекомендуете коллеге-переводчику?", "lo": "ни за что", "hi": "обязательно"},
         "uz": {"q": "Hamkasb tarjimonga tavsiya qilasizmi?", "lo": "aslo", "hi": "albatta"}},
    ],
    "consent": [],
}

FORMS = {"apply": APPLY, "debrief": DEBRIEF}


# ═════════════════════════════════════════════════════════════════════
# Разбор ответа. Одна функция на Telegram и на лист ответов: сервер
# обязан читать ответ так же, как его показывает, — иначе владелец видит
# в письме одно, а по ссылке другое.
# ═════════════════════════════════════════════════════════════════════

def _loc(node: dict, lang: str) -> str:
    """Подпись варианта. Нет узбекского — остаётся русский оригинал, а не
    пустота (тот же закон, что у словаря интерфейса)."""
    if not isinstance(node, dict):
        return ""
    return str(node.get(lang) or node.get("ru") or node.get("v") or "")


def _txt(q: dict, lang: str) -> dict:
    return q.get(lang) or q.get("ru") or {}


def answer_rows(form: dict, answers: dict, lang: str) -> list:
    """Ответы листом: [{n, q, kind, value, chosen}] — по порядку вопросов.

    `chosen` — множество выбранных значений, по нему лист подсвечивает
    варианты; `value` — уже читаемая строка для Telegram."""
    lang = _lang(lang)
    rows = []
    skip = form["T"][lang]["skip"]
    for i, q in enumerate(form["questions"], 1):
        t = _txt(q, lang)
        kind = q["type"]
        if kind == "fields":
            parts = []
            for f in q["fields"]:
                parts.append("%s: %s" % (_loc(f, lang),
                                         str(answers.get(q["id"] + "." + f["k"]) or "").strip() or "—"))
            rows.append({"n": i, "q": t.get("q", ""), "kind": kind, "value": "\n".join(parts),
                         "chosen": set()})
        elif kind == "group":
            parts, chosen = [], set()
            for p in q["parts"]:
                vals = answers.get(q["id"] + "." + p["k"]) or []
                if not isinstance(vals, list):
                    vals = [vals]
                names = []
                for v in vals:
                    chosen.add(str(v))
                    o = next((x for x in p["opts"] if x["v"] == v), None)
                    names.append(_loc(o, lang) if o else str(v))
                parts.append("%s: %s" % (_loc(p, lang), ", ".join(names) or "—"))
            rows.append({"n": i, "q": t.get("q", ""), "kind": kind, "value": "\n".join(parts),
                         "chosen": chosen})
        elif kind == "text":
            val = str(answers.get(q["id"]) or "").strip()
            rows.append({"n": i, "q": t.get("q", ""), "kind": kind, "value": val or skip,
                         "empty": not val, "chosen": set()})
        elif kind == "scale":
            v = answers.get(q["id"])
            rows.append({"n": i, "q": t.get("q", ""), "kind": kind,
                         "value": ("%s/%s" % (v, q["to"])) if v not in (None, "") else "—",
                         "chosen": {str(v)} if v not in (None, "") else set()})
        else:
            v = answers.get(q["id"])
            o = next((x for x in q.get("opts", []) if x["v"] == v), None)
            rows.append({"n": i, "q": t.get("q", ""), "kind": kind,
                         "value": _loc(o, lang) if o else "—",
                         "chosen": {str(v)} if v not in (None, "") else set()})
    return rows


def summary_text(rec: dict, url: str = "") -> str:
    """Лист ответов ПРОСТЫМ текстом — то, что уходит владельцу в Telegram.

    Он же и есть «такой же лист с отвеченными вариантами»: те же номера,
    те же формулировки, что человек видел на экране, плюс ссылка на полный
    лист. Ника получателя здесь нет и быть не может — доставку делает бот
    по числовому id."""
    form = FORMS.get(rec.get("form") or "")
    if not form:
        return ""
    lang = _lang(rec.get("lang"))
    T = form["T"][lang]
    out = [T["title"], "————————————————"]
    who = (rec.get("who") or "").strip()
    if who:
        out.append((form["T"][lang].get("whoLabel") or "Telegram") + ": " + who)
        out.append("")
    for r in answer_rows(form, rec.get("answers") or {}, lang):
        n = "%02d" % r["n"]
        if r["kind"] in ("text", "fields", "group"):
            out.append("%s. %s" % (n, r["q"]))
            out.append(r["value"])
            out.append("")
        else:
            out.append("%s. %s — %s" % (n, r["q"], r["value"]))
    cons = rec.get("consent") or {}
    if form.get("consent"):
        out.append("")
        for c in form["consent"]:
            out.append(("[x] " if cons.get(c["k"]) else "[ ] ") + str(c.get(lang) or c.get("ru")))
    if url:
        out.append("")
        out.append(url)
    return "\n".join(out)


# ═════════════════════════════════════════════════════════════════════
# Страницы
# ═════════════════════════════════════════════════════════════════════

def _shell(title: str, body: str, script: str = "", lang: str = "uz") -> str:
    return ("<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex\">"
            "<title>%s</title>%s<style>%s</style></head><body>%s%s</body></html>"
            % (lang, html.escape(title), FONTS, CSS, body,
               ("<script>%s</script>" % script) if script else ""))


def _topbar(sub: str, lang: str, path: str, counter: bool = False) -> str:
    """Шапка. Переключатель языка — ССЫЛКИ, а не кнопки: страницу открывают
    из Telegram уже на выбранном языке, и ссылка переживает перезагрузку."""
    segs = "".join(
        '<a href="%s?lang=%s"%s>%s</a>' % (path, code, ' aria-pressed="true"' if code == lang else "",
                                           label)
        for code, label in (("uz", "UZ"), ("ru", "RU")))
    return ('<header class="top"><div class="top-in">'
            '<div class="brand">%s<span>%s</span></div>'
            '<div class="right">%s<div class="seg" role="group" aria-label="Til / Язык">%s</div></div>'
            '</div><div class="bar"><i id="bar"></i></div></header>'
            % (BRAND, html.escape(sub),
               '<div class="count" id="count"></div>' if counter else "", segs))


FORM_JS = r"""
var F = __FORM__, LANG = __LANG__, POST = "/api/public/survey", PRE = __PRE__;
var NL = String.fromCharCode(10);
var A = {}, who = PRE.who || "", sent = false, busy = false, token = null;
var app = document.getElementById("app");

function T(){ return F.T[LANG] || F.T.ru; }
function loc(o){ return (o && o[LANG] != null) ? o[LANG] : (o && o.ru != null ? o.ru : (o && o.v) || ""); }
function txt(q){ return q[LANG] || q.ru || {}; }
function el(tag, cls, s){ var e = document.createElement(tag); if(cls) e.className = cls;
  if(s != null) e.textContent = s; return e; }
function pad(n){ return (n < 10 ? "0" : "") + n; }

function filled(q){
  if(q.type === "fields") return q.fields.every(function(f){ return (A[q.id+"."+f.k]||"").trim(); });
  if(q.type === "group") return q.parts.every(function(p){ return !p.req || (A[q.id+"."+p.k]||[]).length; });
  if(q.type === "text") return !!(A[q.id]||"").trim();
  return A[q.id] != null;
}
function progress(){
  var need = 0, got = 0;
  if(F.who){ need++; if(who.trim()) got++; }
  F.questions.forEach(function(q){ if(q.req){ need++; if(filled(q)) got++; } });
  (F.consent||[]).forEach(function(c){ if(c.req){ need++; if(A["c."+c.k]) got++; } });
  var bar = document.getElementById("bar");
  if(bar) bar.style.width = Math.round(got / Math.max(1, need) * 100) + "%";
  var c = document.getElementById("count");
  if(c){ c.textContent = ""; c.appendChild(el("b", null, String(got)));
         c.appendChild(document.createTextNode(" / " + need)); }
}

function chip(name, val, label, multi, qid){
  var lab = el("label", "opt" + (multi ? " box" : ""));
  var inp = document.createElement("input");
  inp.type = multi ? "checkbox" : "radio";
  inp.name = name; inp.value = val;
  inp.checked = multi ? (A[name]||[]).indexOf(val) >= 0 : A[name] === val;
  inp.addEventListener("change", function(){
    if(multi){
      var cur = (A[name]||[]).slice(), i = cur.indexOf(val);
      if(inp.checked && i < 0) cur.push(val); else if(!inp.checked && i >= 0) cur.splice(i,1);
      A[name] = cur;
    } else A[name] = val;
    var card = document.getElementById("q-"+qid);
    if(card) card.classList.remove("miss");
    progress();
  });
  lab.appendChild(inp); lab.appendChild(el("span","tick")); lab.appendChild(el("span",null,label));
  return lab;
}
function optRow(name, opts, multi, qid){
  var box = el("div","opts");
  opts.forEach(function(o){ box.appendChild(chip(name, o.v, loc(o), multi, qid)); });
  return box;
}
function scaleBox(q, t){
  var box = el("div","scale"), row = el("div","scale-row");
  for(var n = q.from; n <= q.to; n++) row.appendChild(chip(q.id, String(n), String(n), false, q.id));
  box.appendChild(row);
  var ends = el("div","ends");
  ends.appendChild(el("span",null, q.from + " — " + (t.lo||"")));
  ends.appendChild(el("span",null, (t.hi||"") + " — " + q.to));
  box.appendChild(ends);
  return box;
}

function render(){
  app.textContent = "";
  if(sent){ renderDone(); progress(); return; }
  var t = T();
  var lede = el("section","lede");
  lede.appendChild(el("p","eyebrow", t.eyebrow));
  lede.appendChild(el("h1", null, t.h1));
  lede.appendChild(el("p", null, t.lede));
  var ul = el("ul","facts");
  (t.facts||[]).forEach(function(f){ ul.appendChild(el("li",null,f)); });
  lede.appendChild(ul);
  app.appendChild(lede);

  if(F.who){
    var w = el("section","who"); w.id = "who";
    var fld = el("div","fld");
    var lb = el("label", null, t.whoLabel); lb.htmlFor = "who-tg";
    var inp = document.createElement("input");
    inp.type = "text"; inp.id = "who-tg"; inp.placeholder = "@username"; inp.value = who;
    inp.addEventListener("input", function(){ who = inp.value; w.classList.remove("miss"); progress(); });
    fld.appendChild(lb); fld.appendChild(inp); w.appendChild(fld);
    w.appendChild(el("p","hint", t.whoHint));
    app.appendChild(w);
  }

  F.questions.forEach(function(q,i){
    var qt = txt(q);
    var card = el("section","q"); card.id = "q-" + q.id;
    var num = el("div","q-n"); num.appendChild(el("b","c" + (i % 4), pad(i+1)));
    card.appendChild(num);
    var main = el("div");
    main.appendChild(el("h2","q-h", qt.q));
    if(qt.s) main.appendChild(el("p","q-sub", qt.s));
    var body = el("div","q-body");
    if(q.type === "fields"){
      var fs = el("div","fields");
      q.fields.forEach(function(f){
        var box = el("div","fld"), id = "f-"+q.id+"-"+f.k;
        var lb2 = el("label", null, loc(f)); lb2.htmlFor = id;
        var inp2 = document.createElement("input");
        inp2.type = "text"; inp2.id = id; inp2.placeholder = f.ph || "";
        inp2.value = A[q.id+"."+f.k] || "";
        inp2.addEventListener("input", function(){
          A[q.id+"."+f.k] = inp2.value; card.classList.remove("miss"); progress(); });
        box.appendChild(lb2); box.appendChild(inp2); fs.appendChild(box);
      });
      body.appendChild(fs);
    } else if(q.type === "group"){
      q.parts.forEach(function(p,pi){
        body.appendChild(el("p","sub-label", loc(p)));
        body.appendChild(optRow(q.id+"."+p.k, p.opts, true, q.id));
        if(pi < q.parts.length - 1) body.appendChild(el("div","gap"));
      });
    } else if(q.type === "text"){
      var ta = document.createElement("textarea");
      ta.placeholder = qt.ph || ""; ta.value = A[q.id] || "";
      ta.addEventListener("input", function(){
        A[q.id] = ta.value; card.classList.remove("miss"); progress(); });
      body.appendChild(ta);
    } else if(q.type === "scale"){
      body.appendChild(scaleBox(q, qt));
    } else {
      body.appendChild(optRow(q.id, q.opts, false, q.id));
    }
    main.appendChild(body); card.appendChild(main); app.appendChild(card);
  });

  if((F.consent||[]).length){
    var cons = el("section","consent");
    F.consent.forEach(function(c){
      var lab = el("label","chk"); lab.id = "c-" + c.k;
      var inp3 = document.createElement("input");
      inp3.type = "checkbox"; inp3.checked = !!A["c."+c.k];
      inp3.addEventListener("change", function(){
        A["c."+c.k] = inp3.checked; lab.classList.remove("miss"); progress(); });
      lab.appendChild(inp3); lab.appendChild(el("span","tick"));
      lab.appendChild(el("span", null, c[LANG] || c.ru));
      cons.appendChild(lab);
    });
    app.appendChild(cons);
  }

  var send = el("div","send");
  var btn = el("button","btn", t.submit); btn.type = "button"; btn.id = "go";
  btn.addEventListener("click", submit);
  send.appendChild(btn);
  var hint = el("p","hint"); hint.id = "hint"; send.appendChild(hint);
  app.appendChild(send);
  progress();
}

function submit(){
  if(busy) return;
  var t = T(), bad = null;
  if(F.who){
    var w = document.getElementById("who");
    if(!who.trim()){ w.classList.add("miss"); bad = t.missWho; } else w.classList.remove("miss");
  }
  F.questions.forEach(function(q,i){
    var card = document.getElementById("q-"+q.id);
    if(q.req && !filled(q)){ card.classList.add("miss"); if(bad === null) bad = t.miss + pad(i+1); }
    else card.classList.remove("miss");
  });
  (F.consent||[]).forEach(function(c){
    var lab = document.getElementById("c-"+c.k);
    if(c.req && !A["c."+c.k]){ lab.classList.add("miss"); if(bad === null) bad = t.missChk; }
    else lab.classList.remove("miss");
  });
  var hint = document.getElementById("hint");
  if(bad !== null){
    hint.className = "hint warn"; hint.textContent = bad;
    var first = document.querySelector(".who.miss") || document.querySelector(".q.miss")
             || document.querySelector(".chk.miss");
    if(first) first.scrollIntoView({behavior:"smooth", block:"center"});
    return;
  }
  var answers = {}, consent = {};
  Object.keys(A).forEach(function(k){
    if(k.indexOf("c.") === 0) consent[k.slice(2)] = !!A[k]; else answers[k] = A[k];
  });
  busy = true;
  var btn = document.getElementById("go");
  btn.disabled = true; btn.textContent = t.sending;
  hint.className = "hint"; hint.textContent = "";
  fetch(POST, {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({form: F.id, lang: LANG, answers: answers, consent: consent,
                          who: who.trim(), ref: PRE.ref || ""})})
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
    .then(function(res){
      busy = false;
      if(!res.ok || !res.j || res.j.ok === false){
        btn.disabled = false; btn.textContent = t.submit;
        hint.className = "hint warn";
        hint.textContent = (res.j && res.j.error) || t.failed;
        return;
      }
      token = res.j.token || null;
      sent = true; render();
      window.scrollTo({top:0, behavior:"smooth"});
    })
    .catch(function(){
      busy = false; btn.disabled = false; btn.textContent = t.submit;
      hint.className = "hint warn"; hint.textContent = t.failed;
    });
}

function renderDone(){
  var t = T();
  var d = el("section","done");
  var st = el("div","stamp");
  st.appendChild(el("span",null,"✓")); st.appendChild(el("span",null,t.done));
  d.appendChild(st);
  d.appendChild(el("h2",null,t.doneH));
  d.appendChild(el("p",null,t.doneP));
  if(token){
    var row = el("div","row");
    var a = el("a","btn ghost", t.mine);
    a.href = "/t/a/" + token + "?lang=" + LANG;
    row.appendChild(a);
    d.appendChild(row);
  }
  app.appendChild(d);
}

render();
"""


def _js(value) -> str:
    """Значение внутри тега <script>.

    `json.dumps` экранирует кавычки, но НЕ последовательность, закрывающую
    сам тег: строка со «</script>» выходит из скрипта в разметку. На этой
    странице такое значение бывает — в анкету приходят `who` и `ref` из
    адреса, — и страницу отдаёт ТОТ ЖЕ адрес, что и приложение, где в
    хранилище браузера лежит токен сессии. Поэтому закрываем и его, и
    открывающую скобку комментария HTML: это единственные две
    последовательности, которыми можно выйти из тега."""
    out = json.dumps(value, ensure_ascii=False)
    # Экранируем ИМЕНЕМ, а не символом: в строке должно остаться шесть знаков
    # \u003c, а не сам «<». JSON.parse и разбор строкового литерала
    # в браузере прочтут их обратно, а разборщик разметки — нет, и выйти
    # из тега станет нечем. U+2028/U+2029 закрыты по той же причине: они
    # обрывают строковый литерал JavaScript, хотя в JSON законны.
    for ch, esc in ((chr(60), chr(92) + 'u003c'), (chr(62), chr(92) + 'u003e'),
                    (chr(38), chr(92) + 'u0026'), (chr(0x2028), chr(92) + 'u2028'),
                    (chr(0x2029), chr(92) + 'u2029')):
        out = out.replace(ch, esc)
    return out


def form_page(form_id: str, lang: str = "uz", pre: dict = None) -> str:
    """Страница опроса. `pre` — то, что уже известно про человека (Telegram
    из бота, метка приглашения): подставить это лучше, чем спрашивать второй
    раз."""
    form = FORMS[form_id]
    lang = _lang(lang)
    T = form["T"][lang]
    payload = {"id": form["id"], "T": form["T"], "questions": form["questions"],
               "consent": form.get("consent") or [], "who": bool(form.get("who"))}
    script = (FORM_JS
              .replace("__FORM__", _js(payload))
              .replace("__LANG__", _js(lang))
              .replace("__PRE__", _js(pre or {})))
    body = (_topbar(T["sub"], lang, form["path"], counter=bool(form.get("who")))
            + '<div class="wrap"><main id="app"></main></div>')
    return _shell(T["title"], body, script, lang)


def answers_page(rec: dict, lang: str = "") -> str:
    """Лист заполненного опроса — тот же вид, только читаемый.

    Ссылку на него получает владелец в Telegram: короткий текст отвечает
    на «что ответили», а лист — на «как это выглядело», включая невыбранные
    варианты. Без них ответ «Терпимо» не значит ничего: непонятно, из чего
    выбирали."""
    form = FORMS.get(rec.get("form") or "")
    if not form:
        return _shell("—", '<div class="wrap"><main id="app"></main></div>')
    lang = _lang(lang or rec.get("lang"))
    T = form["T"][lang]
    parts = [_topbar(T["sub"], lang, "/t/a/" + str(rec.get("token") or ""))]
    parts.append('<div class="wrap"><main>')
    parts.append('<section class="lede"><p class="eyebrow">%s</p><h1>%s</h1><p>%s</p></section>'
                 % (html.escape(T["done"]), html.escape(T["title"]),
                    html.escape(_answers_lede(rec, lang))))
    for i, q in enumerate(form["questions"]):
        row = answer_rows(form, rec.get("answers") or {}, lang)[i]
        qt = _txt(q, lang)
        inner = ['<div class="q-n"><b class="c%d">%02d</b></div><div>' % (i % 4, i + 1),
                 '<h2 class="q-h">%s</h2>' % html.escape(qt.get("q", ""))]
        if qt.get("s"):
            inner.append('<p class="q-sub">%s</p>' % html.escape(qt["s"]))
        inner.append('<div class="q-body">')
        inner.append(_answer_body(q, row, lang))
        inner.append("</div></div>")
        parts.append('<section class="q">%s</section>' % "".join(inner))
    cons = rec.get("consent") or {}
    if form.get("consent"):
        chk = "".join(
            '<div class="chk%s"><span class="tick"></span><span>%s</span></div>'
            % (" on" if cons.get(c["k"]) else "", html.escape(str(c.get(lang) or c.get("ru"))))
            for c in form["consent"])
        parts.append('<section class="consent">%s</section>' % chk)
    parts.append("</main></div>")
    return _shell(T["title"], "".join(parts), "", lang)


def _answers_lede(rec: dict, lang: str) -> str:
    who = (rec.get("who") or "").strip()
    at = rec.get("at") or ""
    if lang == "ru":
        return ("Заполнено %s%s." % (at, (" · " + who) if who else ""))
    return ("To'ldirilgan %s%s." % (at, (" · " + who) if who else ""))


def _answer_body(q: dict, row: dict, lang: str) -> str:
    """Тело ответа в листе. У вариантов показываем ВСЕ, выбранные — отмечены:
    ответ без списка вариантов не читается."""
    kind = q["type"]
    if kind in ("text", "fields"):
        cls = "answer empty" if row.get("empty") else "answer"
        return '<p class="%s">%s</p>' % (cls, html.escape(row["value"]))
    if kind == "group":
        out = []
        for p in q["parts"]:
            out.append('<p class="sub-label">%s</p>' % html.escape(_loc(p, lang)))
            out.append('<div class="opts">%s</div>' % "".join(
                '<span class="opt box %s"><span class="tick"></span><span>%s</span></span>'
                % ("on" if str(o["v"]) in row["chosen"] else "off", html.escape(_loc(o, lang)))
                for o in p["opts"]))
            out.append('<div class="gap"></div>')
        return "".join(out)
    if kind == "scale":
        t = _txt(q, lang)
        cells = "".join(
            '<span class="opt %s">%s</span>' % ("on" if str(n) in row["chosen"] else "off", n)
            for n in range(q["from"], q["to"] + 1))
        return ('<div class="scale"><div class="scale-row">%s</div>'
                '<div class="ends"><span>%s — %s</span><span>%s — %s</span></div></div>'
                % (cells, q["from"], html.escape(t.get("lo", "")),
                   html.escape(t.get("hi", "")), q["to"]))
    return '<div class="opts">%s</div>' % "".join(
        '<span class="opt %s"><span class="tick"></span><span>%s</span></span>'
        % ("on" if str(o["v"]) in row["chosen"] else "off", html.escape(_loc(o, lang)))
        for o in q.get("opts", []))


# ═════════════════════════════════════════════════════════════════════
# Инструкция. ОДНА страница и намеренно короткая: длинную не читают, а
# тестировщику нужно ровно семь шагов от входа до готового файла.
#
# Ни денег, ни имён моделей здесь нет — и это не забывчивость: у тестовых
# организаций и то и другое скрыто (см. `simple` в записи организации),
# и инструкция, называющая цену, показывала бы то, чего человек на экране
# не найдёт.
# ═════════════════════════════════════════════════════════════════════

GUIDE = {
    "ru": {
        "sub": "· как начать",
        "eyebrow": "Инструкция на одну страницу",
        "h1": "Семь шагов от файла до готового перевода",
        "lede": "Ничего настраивать не нужно: всё, что важно, система решает сама. "
                "Прочитайте один раз — дальше по кнопкам.",
        "facts": ["7 шагов", "около 4 минут чтения", "ничего настраивать не надо"],
        "steps": [
            ("Войдите",
             "Логин и пароль вы получили в Telegram. Первым делом загляните в <b>Профиль</b> — "
             "там меняется язык интерфейса и пароль. Язык можно переключить в любой момент."),
            ("Заведите проект и загрузите файл",
             "Вкладка <b>Импорт</b>: назовите проект, выберите пару языков и тему, приложите "
             "<b>.docx</b>. Система сама разрежет документ на сегменты — предложения и абзацы. "
             "Приносите настоящий рабочий текст: на нём видно в разы больше, чем на учебном."),
            ("Нажмите «Перевести и проверить»",
             "Это одна кнопка на весь конвейер: перевод, ревизия, обратная проверка смысла, "
             "сверка терминов, ремонт найденного. Вкладку можно закрыть — работа идёт на сервере, "
             "вернётесь и увидите результат."),
            ("Смотрите на экран «Анализ»",
             "Три строки отвечают на вопрос «что дальше»: <b>Готово</b> — можно выгружать; "
             "<b>Возьмёт прогон</b> — машина доделает сама, просто нажмите ещё раз; "
             "<b>Нужен человек</b> — это к вам. Щёлкните по строке, и таблица покажет "
             "именно эти сегменты."),
            ("Правьте перевод и подтверждайте",
             "В таблице щёлкните по сегменту. Исправили — нажмите <b>Подтвердить</b>: система "
             "запоминает вашу правку, предлагает разослать её по одинаковым местам и учится "
             "на ней. Подтверждённое машина сама не переписывает."),
            ("Ведите глоссарий",
             "Найденные термины ждут вашего решения в очереди. Разница простая: <b>приказ</b> "
             "система обязана соблюсти во всём документе, <b>подсказку</b> модель вправе "
             "проигнорировать. Приказ даёт только человек. Новые термины по умолчанию живут "
             "внутри своего проекта — соседний проект чужую терминологию не подхватит, "
             "пока вы сами не разрешите."),
            ("Выгрузите результат",
             "Вкладка <b>Экспорт</b>, формат <b>«как в оригинале»</b>: вы получите тот же .docx "
             "с вашим переводом — заголовки, таблицы, картинки и колонтитулы останутся на местах."),
        ],
        "notes": [
            "<b>Очередь.</b> Исполнитель прогонов один на всех, но очередь у каждого своя: "
            "задачи идут по кругу между участниками, и длинная книга соседа не задержит вашу "
            "страницу. Пока задача ждёт, в полосе прогона видно, сколько человек впереди.",
            "<b>Если что-то сломалось</b> — не чините обходными путями, а запишите: что нажали, "
            "что ожидали, что получилось. Именно это нам и нужно от теста. В конце попросим "
            "заполнить короткий разбор.",
        ],
    },
    "uz": {
        "sub": "· qanday boshlash kerak",
        "eyebrow": "Bir sahifalik yo'riqnoma",
        "h1": "Fayldan tayyor tarjimagacha yetti qadam",
        "lede": "Hech narsani sozlash kerak emas: muhim narsalarni tizim o'zi hal qiladi. "
                "Bir marta o'qing — keyin tugmalar bo'yicha ishlaysiz.",
        "facts": ["7 qadam", "taxminan 4 daqiqa o'qish", "sozlash shart emas"],
        "steps": [
            ("Kiring",
             "Login va parolni Telegram'da oldingiz. Avvalo <b>Profil</b>ga kiring — u yerda "
             "interfeys tili va parol o'zgartiriladi. Tilni istalgan vaqtda almashtirsa bo'ladi."),
            ("Loyiha oching va fayl yuklang",
             "<b>Import</b> bo'limi: loyihaga nom bering, til juftligi va mavzuni tanlang, "
             "<b>.docx</b> faylni biriktiring. Tizim hujjatni segmentlarga — gap va xatboshilarga "
             "o'zi bo'lib beradi. Haqiqiy ish matningizni olib keling: unda o'quv matnidan ancha "
             "ko'p narsa ko'rinadi."),
            ("«Tarjima qilish va tekshirish» tugmasini bosing",
             "Bu butun konveyer uchun bitta tugma: tarjima, reviziya, ma'noni teskari tekshirish, "
             "atamalarni solishtirish, topilganini ta'mirlash. Oynani yopsangiz ham bo'ladi — ish "
             "serverda ketadi, qaytganingizda natijani ko'rasiz."),
            ("«Tahlil» ekraniga qarang",
             "Uch qator «keyin nima?» degan savolga javob beradi: <b>Tayyor</b> — yuklab olsa "
             "bo'ladi; <b>Ishlov oladi</b> — mashina o'zi tugatadi, yana bir marta bosing; "
             "<b>Odam kerak</b> — bu sizga. Qatorni bosing, jadval aynan shu segmentlarni ko'rsatadi."),
            ("Tarjimani tuzating va tasdiqlang",
             "Jadvalda segmentni bosing. Tuzatdingizmi — <b>Tasdiqlash</b>ni bosing: tizim "
             "tuzatishingizni eslab qoladi, uni bir xil joylarga tarqatishni taklif qiladi va "
             "undan o'rganadi. Tasdiqlanganini mashina o'zi qayta yozmaydi."),
            ("Lug'atni yuriting",
             "Topilgan atamalar navbatda sizning qaroringizni kutadi. Farqi oddiy: <b>buyruq</b>ni "
             "tizim butun hujjatda bajarishi shart, <b>maslahat</b>ni model e'tiborsiz qoldirishi "
             "mumkin. Buyruqni faqat odam beradi. Yangi atamalar sukut bo'yicha o'z loyihasi "
             "ichida yashaydi — qo'shni loyiha o'zga terminologiyani siz ruxsat bermaguningizcha "
             "olmaydi."),
            ("Natijani yuklab oling",
             "<b>Eksport</b> bo'limi, <b>«asl nusxadagidek»</b> formati: o'sha .docx faylni "
             "tarjimangiz bilan olasiz — sarlavhalar, jadvallar, rasmlar va kolontitullar "
             "joyida qoladi."),
        ],
        "notes": [
            "<b>Navbat.</b> Ishlov ijrochisi hammaga bitta, lekin navbat har kimda o'ziniki: "
            "vazifalar ishtirokchilar orasida navbatma-navbat ketadi va qo'shningizning uzun "
            "kitobi sizning sahifangizni ushlab qolmaydi. Vazifa kutayotganda ishlov chizig'ida "
            "oldingizda necha kishi borligi ko'rinadi.",
            "<b>Biror narsa buzilsa</b> — chetlab o'tishga urinmang, yozib qo'ying: nimani "
            "bosdingiz, nimani kutdingiz, nima chiqdi. Sinovdan bizga aynan shu kerak. Oxirida "
            "qisqa tahlilni to'ldirishni so'raymiz.",
        ],
    },
}


def guide_page(lang: str = "uz") -> str:
    lang = _lang(lang)
    g = GUIDE[lang]
    title = BRAND + " " + g["sub"]
    parts = [_topbar(g["sub"], lang, "/t/guide"), '<div class="wrap"><main>']
    parts.append('<section class="lede"><p class="eyebrow">%s</p><h1>%s</h1><p>%s</p>'
                 '<ul class="facts">%s</ul></section>'
                 % (html.escape(g["eyebrow"]), html.escape(g["h1"]), html.escape(g["lede"]),
                    "".join("<li>%s</li>" % html.escape(f) for f in g["facts"])))
    for i, (head, text) in enumerate(g["steps"]):
        parts.append('<section class="step"><div class="q-n"><b class="c%d">%02d</b></div>'
                     '<div><h2>%s</h2><p>%s</p></div></section>'
                     % (i % 4, i + 1, html.escape(head), text))
    for n in g["notes"]:
        parts.append('<p class="note">%s</p>' % n)
    parts.append("</main></div>")
    return _shell(title, "".join(parts), "", lang)


