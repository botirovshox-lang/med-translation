"""Тестовый корпус выгрузки: 30 файлов разных форматов и вёрсток по рецептам.

Зачем: приёмка готового файла (`backend/export_qa.py`, инвариант 44) и правила
чтения/вёрстки проверялись на файлах клиентов, а их мало и они однотипны.
Корпус даёт по файлу на каждый трудный случай — колонки, таблицы, стихи
с разрядкой, инфографика, формы, повёрнутый текст, письмо справа налево,
иероглифы, Word/Excel/PowerPoint/HTML/субтитры — и десять «трудночитаемых»:
обгоревшее письмо, рукопись, рецепт врача, выцветший машинописный скан,
ксерокопия, мятый чек, старая газета со сквозным оборотом, табличка под
углом, факс, залитая водой страница.

Детерминированно (семя на файл) и только шрифтами из репозитория, чтобы
корпус гонялся как регрессия и на сервере, и здесь. Текст клиентов сюда
не попадает: всё написано для корпуса.

  python tools/corpus_build.py OUT_DIR [--only id1,id2] [--set2]

Рядом с файлами пишется `manifest.json`: язык оригинала и перевода, формат
выгрузки, вид файла и что именно он проверяет — его читает
`tools/corpus_run.py`.
"""
from __future__ import annotations

import io
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "frontend" / "vendor" / "fonts" / "sub"
F = {
    "sans": FONTS / "NotoSans-Regular.ttf",
    "sansb": FONTS / "NotoSans-Bold.ttf",
    "sansc": FONTS / "NotoSans-Condensed.ttf",
    "serif": FONTS / "NotoSerif-Regular.ttf",
    "serifb": FONTS / "NotoSerif-Bold.ttf",
    "mono": FONTS / "LiberationMono-Regular.ttf",
    "monob": FONTS / "LiberationMono-Bold.ttf",
    "hand": FONTS / "MarckScript-Regular.ttf",
    "old": FONTS / "OldStandard-Regular.ttf",
    "oldb": FONTS / "OldStandard-Bold.ttf",
    "dejavu": FONTS / "DejaVuSans.ttf",
    "dejavub": FONTS / "DejaVuSans-Bold.ttf",
    "cjk": FONTS / "NotoSansSC-Regular.otf",
}

# ─── тексты ─────────────────────────────────────────────────────────────

NEWS_HEAD = "Город переходит на электробусы"
NEWS_LEAD = ("С первого марта на маршруты выйдут сорок новых электробусов. "
             "Мэрия обещает, что стоимость проезда не изменится.")
NEWS_COLS = [
    "Первые машины уже прошли испытания на северных линиях. Водители отмечают, "
    "что электробус разгоняется плавнее дизельного автобуса, а в салоне заметно "
    "тише. Зарядные станции построены на трёх конечных остановках, полная зарядка "
    "занимает около четырёх часов.",
    "По расчётам транспортного управления, город сэкономит на топливе до "
    "двенадцати миллионов рублей в год. Часть средств пойдёт на ремонт "
    "остановочных павильонов и установку электронных табло с расписанием.",
    "Жители спальных районов просят продлить работу ночных маршрутов. "
    "В управлении ответили, что вопрос рассмотрят после первого квартала, "
    "когда будут готовы данные о пассажиропотоке.",
]
NEWS_QUOTE = "«Тишина в салоне — первое, что замечают пассажиры»"

ARTICLE_TITLE = "Влияние физической нагрузки на уровень глюкозы у пациентов с диабетом 2 типа"
ARTICLE_AUTHORS = "И. П. Сафронова¹, Д. А. Ким², Л. Р. Хасанова¹"
ARTICLE_ABSTRACT = ("Цель исследования — оценить изменение гликированного гемоглобина (HbA1c) "
                    "после 12 недель регулярной ходьбы. В исследование включены 64 пациента "
                    "в возрасте 45–70 лет. Снижение HbA1c составило 0,6 ± 0,2 % (p < 0,01).")
ARTICLE_BODY = [
    "Введение. Сахарный диабет 2 типа остаётся одной из главных причин сердечно-сосудистых "
    "осложнений. Физическая активность повышает чувствительность тканей к инсулину и "
    "снижает потребность в препаратах.",
    "Методы. Участники ходили по 30 минут 5 раз в неделю. Дозировку метформина не меняли. "
    "Глюкозу натощак измеряли каждые две недели; концентрацию выражали в ммоль/л, "
    "площадь под кривой — в ммоль·ч/л.",
    "Результаты. Средняя глюкоза снизилась с 8,4 до 7,1 ммоль/л. У ¹/₃ пациентов "
    "удалось уменьшить дозу препарата. Индекс массы тела изменился незначительно "
    "(29,8 ± 3,1 против 29,1 ± 3,0 кг/м²).",
]
ARTICLE_REFS = [
    "1. American Diabetes Association. Standards of Care in Diabetes — 2024. Diabetes Care. 2024;47(Suppl 1):S1–S321.",
    "2. Иванов С. Н., Петрова О. В. Физическая реабилитация при метаболическом синдроме. М.: Медицина, 2019. 212 с.",
    "3. Colberg SR, et al. Exercise and type 2 diabetes. Diabetes Care. 2010;33(12):e147–e167.",
]

POEM_TITLE = "ОСЕННЕЕ УТРО"
POEM_EPIGRAPH = ("И дым отечества нам сладок и приятен.", "А. С. Грибоедов")
POEM = [
    ["Туман над рекою, как лёгкая шаль,", "Укрыл берега до холмов,",
     "И тянет из рощи прохладная даль", "Последней листвой и дымком."],
    ["Скрипит у колодца продрогший журавль,", "Петух пробудился в селе,",
     "И солнце, как будто нарочно, слегка", "Коснулось росы на стекле."],
]

INVOICE = {
    "seller": "ООО «Северный ветер»", "inn": "ИНН 7701234567",
    "title": "СЧЁТ № 148 от 12 октября 2026 г.",
    "buyer": "Покупатель: ИП Каримов А. Б., г. Ташкент, ул. Навои, 15",
    "rows": [("Бумага офисная А4, 500 листов", "20", "уп.", "350,00", "7 000,00"),
             ("Картридж для принтера, чёрный", "4", "шт.", "2 150,00", "8 600,00"),
             ("Папка-регистратор, 75 мм", "12", "шт.", "190,00", "2 280,00"),
             ("Доставка по городу", "1", "усл.", "500,00", "500,00")],
    "total": "Итого к оплате: 18 380,00 руб.",
    "words": "Восемнадцать тысяч триста восемьдесят рублей 00 копеек",
    "sign": "Руководитель ________________ / Орлов В. С. /",
}

INFO = {
    "title": "Как правильно мыть руки",
    "steps": [("1", "Смочите руки тёплой водой"), ("2", "Нанесите мыло на ладони"),
              ("3", "Трите не меньше 20 секунд"), ("4", "Промойте между пальцами"),
              ("5", "Смойте пену проточной водой"), ("6", "Вытрите руки чистым полотенцем")],
    "note": "Мойте руки перед едой, после улицы и после контакта с животными.",
    "badge": "20 сек",
}

BROCHURE = {
    "title": "Санаторий «Горный воздух»",
    "panels": [
        ("О нас", "Санаторий расположен на высоте 1200 метров в сосновом лесу. "
                  "Мы принимаем гостей круглый год и предлагаем программы оздоровления "
                  "для взрослых и детей."),
        ("Процедуры", "Минеральные ванны, лечебный массаж, ингаляции, "
                      "соляная пещера, лечебная физкультура под контролем врача."),
        ("Контакты", "Бронирование: +7 (812) 555-01-23. Адрес: посёлок Сосновый, "
                     "ул. Лесная, 8. Трансфер от вокзала бесплатно."),
    ],
    "side": "Отдых, который лечит",
}

FORM = {
    "title": "ЗАЯВЛЕНИЕ НА ПОЛУЧЕНИЕ ПРОПУСКА",
    "fields": ["Фамилия, имя, отчество", "Дата рождения", "Должность", "Отдел",
               "Номер телефона", "Срок действия пропуска"],
    "checks": ["Постоянный пропуск", "Временный пропуск", "Пропуск для автомобиля"],
    "foot": "Подпись заявителя ____________   Дата «___» __________ 20__ г.",
}

MENU = {
    "title": "Меню ресторана «Чайхана»",
    "sections": [
        ("Горячие блюда", [("Плов по-ташкентски", "с бараниной и нутом", "420"),
                           ("Лагман", "домашняя лапша, говядина, овощи", "380"),
                           ("Шашлык из баранины", "подаётся с луком и лепёшкой", "560")]),
        ("Напитки", [("Зелёный чай", "чайник 0,7 л", "150"),
                     ("Компот из сухофруктов", "стакан 0,3 л", "120")]),
    ],
    "note": "Острые блюда отмечены знаком ★. Обслуживание — 10 %.",
}

PROSE_HEAD = "Глава третья. Дорога в горы"
PROSE = [
    "Утром мы вышли из посёлка, когда солнце ещё не поднялось над хребтом. Тропа сначала "
    "шла вдоль реки, потом свернула в ущелье, где пахло мокрым камнем и мятой. Проводник "
    "шёл впереди, изредка останавливаясь, чтобы показать нам следы горного козла.",
    "К полудню подъём стал круче. Мы шли медленно, берегли дыхание и почти не "
    "разговаривали. Внизу остались сады и крыши посёлка, а впереди открывались "
    "снежные вершины, которые с каждым поворотом казались всё ближе.",
    "Привал устроили у родника. Вода была такой холодной, что сводило зубы, но "
    "никто не отказался наполнить флягу. Проводник рассказал, что этой тропой "
    "когда-то ходили торговые караваны, и показал старую каменную стену, "
    "заросшую мхом и лишайником.",
    "Вечером мы добрались до хижины. Ветер усилился, и стены тихо поскрипывали. "
    "Мы развели огонь в печке, сварили кашу и долго сидели у окна, глядя, как "
    "последние лучи гаснут на снегу.",
]

EN_GUIDE = {
    "title": "Quick Start Guide: Smart Thermostat T200",
    "steps": ["Turn off the power at the circuit breaker before installation.",
              "Remove the old thermostat and label each wire with the stickers provided.",
              "Mount the base plate and connect the wires to the matching terminals.",
              "Attach the display, restore power and follow the on-screen setup."],
    "table": [("Mode", "Range", "Default"), ("Heating", "5–30 °C", "21 °C"),
              ("Cooling", "16–32 °C", "24 °C"), ("Eco", "10–28 °C", "18 °C")],
    "warn": "Warning: do not install near a heat source or in direct sunlight.",
}

CERT = {
    "title": "СЕРТИФИКАТ",
    "sub": "о прохождении курса повышения квалификации",
    "name": "Абдуллаева Малика Рустамовна",
    "body": "успешно завершила курс «Неотложная помощь в педиатрии» в объёме 72 часов",
    "date": "Ташкент, 20 сентября 2026 г.",
    "sign": "Директор учебного центра  ________  Н. В. Громов",
}

REPORT_DOCX = {
    "title": "Отчёт о работе отделения за третий квартал",
    "p1": ["За отчётный период в отделение поступило ", ("412 пациентов", "b"),
           ", что на ", ("8 %", "b"), " больше, чем во втором квартале. Средний срок "
           "лечения составил ", ("9,2 дня", "i"), "."],
    "p2": ["Основные причины госпитализации: ", ("пневмония", "red"), ", обострение "
           "хронической обструктивной болезни лёгких и ", ("бронхиальная астма", "red"), "."],
    "bullets": ["Внедрена электронная история болезни.", "Проведено обучение среднего медперсонала.",
                "Закуплены два новых аппарата искусственной вентиляции лёгких."],
    "table": [("Показатель", "II квартал", "III квартал"), ("Поступило пациентов", "381", "412"),
              ("Летальность, %", "1,8", "1,4"), ("Средний койко-день", "9,7", "9,2")],
    "footnote": "Данные приведены без учёта дневного стационара.",
    "header": "ГБУЗ «Городская клиническая больница № 5»",
}

LETTER_DOCX = {
    "org": "Министерство здравоохранения", "dept": "Управление кадров",
    "to": "Главному врачу\nобластной больницы\nгосподину Юсупову Р. Т.",
    "subj": "О направлении специалистов на стажировку",
    "body": ["Уважаемый Рустам Тахирович!",
             "Просим направить двух врачей-реаниматологов для прохождения стажировки "
             "в республиканском центре экстренной медицинской помощи с 1 по 30 ноября "
             "2026 года. Проживание и питание участников обеспечивает принимающая сторона.",
             "Список кандидатов просим представить до 25 октября."],
    "sign": "С уважением,\nначальник управления  А. С. Миронова",
}

BUDGET_XLSX = [
    ("Статья расходов", "Январь", "Февраль", "Март", "Итого за квартал", "Комментарий"),
    ("Аренда помещения", 120000, 120000, 120000, None, "Договор продлён до конца года"),
    ("Заработная плата", 845000, 851000, 860000, None, "С учётом премии за план"),
    ("Коммунальные услуги", 38500, 41200, 35700, None, "Отопление в феврале выше нормы"),
    ("Реклама в интернете", 60000, 45000, 70000, None, "Весенняя кампания стартовала в марте"),
    ("Канцелярские товары", 7300, 5100, 6800, None, ""),
]

SLIDES = [
    ("Стратегия развития на 2027 год", ["Выход на рынки Центральной Азии",
                                       "Запуск мобильного приложения",
                                       "Снижение затрат на логистику на 15 %"]),
    ("Ключевые показатели", ["Выручка: 1,2 млрд руб. (+18 %)", "Новые клиенты: 3 400",
                             "Удержание клиентов: 87 %"]),
    ("Следующие шаги", ["Утвердить бюджет до 1 декабря", "Нанять руководителя проекта",
                        "Подготовить пилот в двух городах"]),
]

HTML_EN = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Visiting the Botanical Garden</title></head>
<body>
<nav><a href="/">Home</a> | <a href="/plan">Plan your visit</a> | <a href="/events">Events</a></nav>
<h1>Visiting the Botanical Garden</h1>
<p>The garden is open <b>every day from 9 am to 7 pm</b>. Last entry is one hour before closing.</p>
<h2>Tickets</h2>
<ul>
<li>Adults — <strong>$12</strong></li>
<li>Children under 12 — free with an adult</li>
<li>Students and seniors — $8 with a valid ID</li>
</ul>
<p>The tropical greenhouse is <em>temporarily closed</em> for renovation until <time>March 2027</time>.
Guided tours start at the main gate at 11 am and 3 pm.</p>
<table><tr><th>Season</th><th>What to see</th></tr>
<tr><td>Spring</td><td>Tulips, magnolias and cherry blossoms</td></tr>
<tr><td>Autumn</td><td>Maples and the chrysanthemum show</td></tr></table>
<footer>© 2026 City Botanical Garden. Please do not pick the flowers.</footer>
</body></html>
"""

MD_RU = """# Инструкция по установке программы «Учёт склада»

## Системные требования

- Windows 10 или новее
- 4 ГБ оперативной памяти
- **500 МБ** свободного места на диске

## Установка

1. Скачайте установщик с сайта компании.
2. Запустите файл `setup.exe` от имени администратора.
3. Следуйте указаниям мастера установки.

> Важно: перед обновлением сделайте резервную копию базы данных.

Вопросы и предложения присылайте на адрес support@example.com.
"""

SRT_RU = """1
00:00:01,000 --> 00:00:03,500
Добрый день! Сегодня мы расскажем о том,

2
00:00:03,600 --> 00:00:06,800
как правильно ухаживать за комнатными растениями.

3
00:00:07,200 --> 00:00:10,400
Большинство растений не любят прямых солнечных лучей.

4
00:00:10,500 --> 00:00:13,900
Поливать их лучше утром, отстоянной водой комнатной температуры.

5
00:00:14,300 --> 00:00:17,000
А зимой полив нужно сократить вдвое.
"""

UI_SHOT = {
    "title": "Личный кабинет", "menu": ["Главная", "Заказы", "Платежи", "Настройки", "Выход"],
    "card": ("Баланс", "12 450,00 ₽"), "btn": ["Пополнить", "История операций"],
    "rows": [("15.10", "Оплата заказа № 5521", "−1 200,00"), ("14.10", "Пополнение картой", "+5 000,00"),
             ("12.10", "Возврат за отменённый заказ", "+340,00")],
    "hint": "Уведомления о платежах приходят на почту и в мобильное приложение.",
}

POSTER = {"title": "ФЕСТИВАЛЬ УЛИЧНОЙ ЕДЫ", "date": "18–20 октября", "place": "Парк Горького",
          "sub": "Более 60 кухонь мира, живая музыка и мастер-классы для детей",
          "free": "Вход свободный"}

# трудночитаемые
BURNT_LETTER = ["Дорогая Анна!",
                "Пишу тебе из госпиталя. Рана заживает, врачи",
                "говорят, что через месяц меня выпишут. Кормят",
                "хорошо, по вечерам читаем вслух газеты.",
                "Передай маме, чтобы не волновалась, и поцелуй",
                "за меня маленького Петю. Скоро увидимся.",
                "Твой Николай. 14 марта 1943 года."]
HAND_NOTE = ["Маша, привет!", "Я ушла в магазин, вернусь к шести.",
             "Суп в холодильнике, разогрей.", "Не забудь покормить кота",
             "и позвонить бабушке!", "Целую, мама"]
RX_HEAD = ["Городская поликлиника № 12", "РЕЦЕПТ"]
RX_HAND = ["Пациент: Ахмедов Т. Р., 54 года", "Амоксициллин 500 мг",
           "по 1 таблетке 3 раза в день 7 дней", "Ибупрофен 200 мг при боли",
           "Повторный приём через неделю"]
TYPEWRITER = ["ПРИКАЗ № 37", "по Опытной станции", "12 июня 1958 года",
              "В связи с началом уборочной кампании",
              "ПРИКАЗЫВАЮ:", "1. Перевести работников полевых бригад",
              "   на удлинённый рабочий день.",
              "2. Обеспечить бригады питьевой водой",
              "   и горячим питанием.", "3. Контроль возложить на агронома",
              "   тов. Лебедева С. И.", "Директор станции   П. Н. Гаврилов"]
PHOTOCOPY = {"title": "График дежурств на ноябрь",
             "rows": [("Дата", "Врач", "Отделение"), ("01.11", "Соколов А. А.", "Терапия"),
                      ("02.11", "Мирзаева Д. К.", "Хирургия"), ("03.11", "Лим В. О.", "Кардиология"),
                      ("04.11", "Зуева Т. П.", "Неврология")],
             "note": "Замены согласовывать с заведующим."}
RECEIPT = ["МАГАЗИН «ПРОДУКТЫ 24»", "г. Самарканд, ул. Регистан, 3",
           "КАССОВЫЙ ЧЕК № 0457", "Молоко 3,2 % 1 л      14 500",
           "Хлеб белый            6 000", "Яблоки 1,2 кг         21 600",
           "Сыр твёрдый 0,3 кг    38 400", "ИТОГО                80 500",
           "Наличными           100 000", "Сдача                19 500",
           "Спасибо за покупку!"]
OLD_NEWS = {"title": "ВѢСТИ ДНЯ", "cols": [
    "Вчера въ городскомъ саду состоялось открытіе новой библіотеки для народа. "
    "На торжество собралось много публики, играла музыка пожарной команды.",
    "Городская управа извѣщаетъ, что съ перваго числа будущаго мѣсяца "
    "начнутся работы по замощенію Большой улицы. Проѣздъ будетъ закрытъ."]}
SIGN = ["ВНИМАНИЕ!", "Проход по территории", "строительной площадки", "ЗАПРЕЩЁН",
        "Обход справа по тротуару"]
FAX = ["URGENT — PLEASE FORWARD", "To: Dr. Elena Markova, Cardiology Dept.",
       "From: City Laboratory, tel. 555-0198", "Patient: Robert Lin, DOB 03/11/1961",
       "Troponin I: 0.08 ng/mL (reference < 0.04)", "Potassium: 5.6 mmol/L (high)",
       "Please call back to confirm receipt.", "Page 1 of 1"]
WATER = ["Дорогой дневник!", "Сегодня весь день шёл дождь, и мы не пошли",
         "на речку. Папа починил велосипед, а я помогала", "держать инструменты.",
         "Вечером пекли пирог с яблоками. Он получился", "немного подгоревшим, но очень вкусным."]


# ─── PDF (reportlab) ───────────────────────────────────────────────────

def _rl_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for k, p in F.items():
        if str(p).endswith(".otf"):
            continue                    # CFF-шрифт reportlab не берёт; он только для картинок
        try:
            pdfmetrics.getFont(k)
        except KeyError:
            pdfmetrics.registerFont(TTFont(k, str(p)))


def _wrap(c, text, font, size, width):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if stringWidth(t, font, size) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _para(c, text, x, y, width, font="serif", size=10, lead=None, align="left", indent=0.0,
          color=(0.1, 0.1, 0.1)):
    """Абзац; возвращает y под ним. align: left|justify|center|right."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    lead = lead or size * 1.3
    c.setFillColorRGB(*color)
    lines = _wrap(c, text, font, size, width - indent)
    for k, ln in enumerate(lines):
        xx = x + (indent if k == 0 else 0)
        ww = width - (indent if k == 0 else 0)
        if align == "justify" and k < len(lines) - 1 and " " in ln:
            words = ln.split()
            gap = (ww - sum(stringWidth(w, font, size) for w in words)) / (len(words) - 1)
            cx = xx
            for w in words:
                c.setFont(font, size)
                c.drawString(cx, y, w)
                cx += stringWidth(w, font, size) + gap
        elif align == "center":
            c.setFont(font, size)
            c.drawCentredString(x + width / 2, y, ln)
        elif align == "right":
            c.setFont(font, size)
            c.drawRightString(x + width, y, ln)
        else:
            c.setFont(font, size)
            c.drawString(xx, y, ln)
        y -= lead
    return y


def pdf_newspaper(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    c.setFont("serifb", 9)
    c.drawString(40, H - 30, "ГОРОДСКИЕ НОВОСТИ")
    c.drawRightString(W - 40, H - 30, "Пятница, 23 октября 2026 · № 204")
    c.setLineWidth(1.2)
    c.line(40, H - 36, W - 40, H - 36)
    c.setFont("serifb", 26)
    c.drawString(40, H - 72, NEWS_HEAD)
    y = _para(c, NEWS_LEAD, 40, H - 96, W - 80, "serif", 13, 17, color=(0.25, 0.25, 0.25))
    c.line(40, y + 4, W - 40, y + 4)
    colw, gap = (W - 80 - 2 * 18) / 3, 18
    top = y - 14
    for i, t in enumerate(NEWS_COLS):
        x = 40 + i * (colw + gap)
        yy = top
        if i == 0:
            # буквица
            c.setFont("serifb", 34)
            c.drawString(x, yy - 22, t[0])
            lines = _wrap(c, t[1:], "serif", 10, colw - 30)
            c.setFont("serif", 10)
            for k, ln in enumerate(lines):
                if k < 2:
                    c.drawString(x + 28, yy, ln)
                    yy -= 13
                else:
                    break
            rest = " ".join(lines[2:])
            yy = _para(c, rest, x, yy, colw, "serif", 10, 13, align="justify")
        else:
            yy = _para(c, t, x, yy, colw, "serif", 10, 13, align="justify")
        if i == 1:
            c.setFillColorRGB(0.85, 0.1, 0.1)
            c.rect(x, yy - 60, colw, 3, fill=1, stroke=0)
            _para(c, NEWS_QUOTE, x, yy - 76, colw, "serifb", 12, 15, color=(0.6, 0.05, 0.05))
    # фото-заглушка с подписью
    c.setFillColorRGB(0.75, 0.8, 0.85)
    c.rect(40, 200, W - 80, 180, fill=1, stroke=0)
    c.setFillColorRGB(0.3, 0.35, 0.4)
    c.circle(W / 2, 290, 40, fill=1, stroke=0)
    _para(c, "Новый электробус на испытаниях. Фото пресс-службы мэрии.", 40, 186, W - 80,
          "sans", 8, 10, color=(0.35, 0.35, 0.35))
    c.setFont("sans", 8)
    c.drawCentredString(W / 2, 30, "3")
    c.save()


def pdf_article(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    c.setFont("sans", 7.5)
    c.drawString(50, H - 28, "Медицинский вестник. 2026. Т. 14, № 3. С. 45–49")
    c.drawRightString(W - 50, H - 28, "DOI: 10.1234/mv.2026.3.45")
    y = _para(c, ARTICLE_TITLE, 50, H - 64, W - 100, "serifb", 15, 19)
    c.setFont("serif", 10)
    c.drawString(50, y - 4, ARTICLE_AUTHORS)
    c.setFont("sans", 7.5)
    c.drawString(50, y - 18, "¹ Медицинский университет, Казань; ² Городская больница № 2, Ташкент")
    # реферат в рамке с заливкой
    by = y - 34
    lines = _wrap(c, "Резюме. " + ARTICLE_ABSTRACT, "sans", 9, W - 120)
    bh = len(lines) * 12 + 14
    c.setFillColorRGB(0.93, 0.95, 0.98)
    c.setStrokeColorRGB(0.5, 0.6, 0.75)
    c.rect(50, by - bh, W - 100, bh, fill=1, stroke=1)
    _para(c, "Резюме. " + ARTICLE_ABSTRACT, 60, by - 14, W - 120, "sans", 9, 12)
    y = by - bh - 20
    colw = (W - 100 - 20) / 2
    cols = [ARTICLE_BODY[:2], ARTICLE_BODY[2:]]
    ends = []
    for i, ps in enumerate(cols):
        yy = y
        x = 50 + i * (colw + 20)
        for p in ps:
            yy = _para(c, p, x, yy, colw, "serif", 9.5, 12.5, align="justify", indent=12) - 4
        if i == 1:
            # формула
            c.setFont("serif", 11)
            c.drawCentredString(x + colw / 2, yy - 10, "ИМТ = m / h²,   ΔHbA1c = −0,6 ± 0,2 %")
            c.setFont("serif", 8)
            c.drawRightString(x + colw, yy - 10, "(1)")
            yy -= 30
        ends.append(yy)
    y = min(ends) - 10
    c.setFont("sansb", 9)
    c.drawString(50, y, "Литература")
    y -= 14
    for r in ARTICLE_REFS:
        y = _para(c, r, 50, y, W - 100, "sans", 8, 10) - 2
    c.setLineWidth(0.5)
    c.line(50, 70, 150, 70)
    _para(c, "Конфликт интересов: авторы заявляют об отсутствии конфликта интересов.", 50, 58,
          W - 100, "sans", 7, 9)
    c.save()


def pdf_invoice(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    # логотип
    c.setFillColorRGB(0.1, 0.4, 0.7)
    c.circle(70, H - 70, 22, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("sansb", 16)
    c.drawCentredString(70, H - 76, "СВ")
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("sansb", 12)
    c.drawString(100, H - 64, INVOICE["seller"])
    c.setFont("sans", 9)
    c.drawString(100, H - 78, INVOICE["inn"] + " · г. Москва, Ленинский пр., 42")
    c.setFont("sansb", 15)
    c.drawCentredString(W / 2, H - 130, INVOICE["title"])
    c.setFont("sans", 10)
    c.drawString(50, H - 160, INVOICE["buyer"])
    heads = ["Наименование товара", "Кол-во", "Ед.", "Цена", "Сумма"]
    xs = [50, 300, 360, 410, 480, W - 50]
    y = H - 190
    c.setFillColorRGB(0.88, 0.9, 0.94)
    c.rect(50, y - 6, W - 100, 20, fill=1, stroke=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("sansb", 9)
    for k, h in enumerate(heads):
        c.drawString(xs[k] + 4, y, h)
    c.setLineWidth(0.6)
    rows_top = y + 14
    y -= 22
    c.setFont("sans", 9)
    for r in INVOICE["rows"]:
        for k, v in enumerate(r):
            if k >= 3:
                c.drawRightString(xs[k + 1] - 4, y, v)
            else:
                c.drawString(xs[k] + 4, y, v)
        y -= 20
    for x in xs:
        c.line(x, rows_top, x, y + 14)
    for yy in [rows_top] + [rows_top - 20 - 20 * k for k in range(len(INVOICE["rows"]) + 1)]:
        c.line(50, yy, W - 50, yy)
    c.setFont("sansb", 11)
    c.drawRightString(W - 50, y - 10, INVOICE["total"])
    c.setFont("sans", 9)
    c.drawString(50, y - 30, INVOICE["words"])
    c.drawString(50, y - 90, INVOICE["sign"])
    # печать
    c.setStrokeColorRGB(0.2, 0.3, 0.75)
    c.setLineWidth(2)
    c.circle(330, y - 80, 38, fill=0, stroke=1)
    c.setFont("sans", 7)
    c.setFillColorRGB(0.2, 0.3, 0.75)
    c.drawCentredString(330, y - 78, "ДЛЯ СЧЕТОВ")
    c.save()


def pdf_infographic(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    c.setFillColorRGB(0.05, 0.45, 0.55)
    c.rect(0, H - 110, W, 110, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("sansb", 28)
    c.drawString(40, H - 70, INFO["title"])
    cols = [(0.95, 0.55, 0.15), (0.2, 0.6, 0.3), (0.25, 0.45, 0.8)]
    bw, bh = (W - 80 - 2 * 20) / 3, 150
    for i, (num, txt) in enumerate(INFO["steps"]):
        r, k = divmod(i, 3)
        x = 40 + k * (bw + 20)
        y = H - 150 - (r + 1) * (bh + 25)
        col = cols[k]
        c.setFillColorRGB(*col)
        c.roundRect(x, y, bw, bh, 12, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.circle(x + 26, y + bh - 26, 16, fill=1, stroke=0)
        c.setFillColorRGB(*col)
        c.setFont("sansb", 16)
        c.drawCentredString(x + 26, y + bh - 32, num)
        _para(c, txt, x + 14, y + bh - 68, bw - 28, "sansb", 13, 16, color=(1, 1, 1))
        if k < 2:
            c.setStrokeColorRGB(0.4, 0.4, 0.4)
            c.setLineWidth(2)
            ax = x + bw + 2
            c.line(ax, y + bh / 2, ax + 16, y + bh / 2)
            c.line(ax + 10, y + bh / 2 + 5, ax + 16, y + bh / 2)
            c.line(ax + 10, y + bh / 2 - 5, ax + 16, y + bh / 2)
    # значок времени
    c.setFillColorRGB(0.85, 0.1, 0.2)
    c.circle(W - 90, 150, 46, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("sansb", 16)
    c.drawCentredString(W - 90, 145, INFO["badge"])
    _para(c, INFO["note"], 40, 170, W - 200, "sans", 12, 16, color=(0.15, 0.15, 0.15))
    c.save()


def pdf_verse(path):
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A5)
    W, H = A5
    # заголовок вразрядку
    t = c.beginText()
    t.setFont("oldb", 16)
    t.setCharSpace(6)
    from reportlab.pdfbase.pdfmetrics import stringWidth
    wt = stringWidth(POEM_TITLE, "oldb", 16) + 6 * (len(POEM_TITLE) - 1)
    t.setTextOrigin((W - wt) / 2, H - 70)
    t.textLine(POEM_TITLE)
    c.drawText(t)
    t2 = c.beginText()
    t2.setCharSpace(0)
    c.drawText(t2)
    c.setFont("old", 9.5)
    c.drawRightString(W - 40, H - 100, POEM_EPIGRAPH[0])
    c.drawRightString(W - 40, H - 113, POEM_EPIGRAPH[1])
    y = H - 150
    for st in POEM:
        for k, ln in enumerate(st):
            # стихи набраны с лёгкой разрядкой, как в старых изданиях (Ч6)
            tl = c.beginText()
            tl.setFont("old", 10.5)
            tl.setCharSpace(1.1)
            tl.setTextOrigin(52 + (14 if k % 2 else 0), y)
            tl.textLine(ln)
            c.drawText(tl)
            y -= 17
        y -= 14
    c.setFont("old", 12)
    c.drawCentredString(W / 2, y - 6, "* * *")
    c.setFont("old", 9)
    c.drawCentredString(W / 2, 28, "— 17 —")
    c.save()


def pdf_brochure(path):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    _rl_fonts()
    W, H = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=(W, H))
    pw = W / 3
    for i, (head, body) in enumerate(BROCHURE["panels"]):
        x = i * pw
        if i == 1:
            c.setFillColorRGB(0.92, 0.96, 0.9)
            c.rect(x, 0, pw, H, fill=1, stroke=0)
        c.setFillColorRGB(0.15, 0.4, 0.2)
        c.setFont("sansb", 18)
        c.drawString(x + 30, H - 70, head)
        _para(c, body, x + 30, H - 100, pw - 70, "sans", 11, 15, color=(0.15, 0.15, 0.15))
    # повёрнутый текст вдоль кромки
    c.saveState()
    c.translate(pw - 14, 60)
    c.rotate(90)
    c.setFillColorRGB(0.15, 0.4, 0.2)
    c.setFont("sansb", 13)
    c.drawString(0, 0, BROCHURE["side"])
    c.restoreState()
    c.saveState()
    c.translate(2 * pw + pw / 2 - 45, 150)
    c.rotate(15)
    c.setFillColorRGB(0.85, 0.3, 0.1)
    c.setFont("sansb", 19)
    c.drawCentredString(0, 0, BROCHURE["title"])
    c.restoreState()
    c.save()


def pdf_form(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    c.setFont("sansb", 14)
    c.drawCentredString(W / 2, H - 70, FORM["title"])
    y = H - 120
    c.setLineWidth(0.7)
    for f in FORM["fields"]:
        c.setFont("sans", 10)
        c.drawString(50, y, f + ":")
        c.line(230, y - 2, W - 50, y - 2)
        y -= 34
    y -= 10
    c.setFont("sansb", 10)
    c.drawString(50, y, "Вид пропуска (отметьте):")
    y -= 24
    for k, ch in enumerate(FORM["checks"]):
        c.rect(60, y - 2, 11, 11, fill=0, stroke=1)
        if k == 1:
            c.line(61, y + 3, 65, y - 1)
            c.line(65, y - 1, 71, y + 9)
        c.setFont("sans", 10)
        c.drawString(80, y, ch)
        y -= 22
    c.setFont("sans", 10)
    c.drawString(50, y - 40, FORM["foot"])
    c.setFont("sans", 7.5)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(50, 40, "Форма П-2 · утверждена приказом от 01.02.2025 № 14")
    c.save()


def pdf_menu(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase.pdfmetrics import stringWidth
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    c.setFillColorRGB(0.98, 0.95, 0.88)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColorRGB(0.45, 0.2, 0.05)
    c.setFont("serifb", 24)
    c.drawCentredString(W / 2, H - 70, MENU["title"])
    y = H - 120
    for sec, items in MENU["sections"]:
        c.setFillColorRGB(0.6, 0.15, 0.1)
        c.setFont("serifb", 15)
        c.drawString(60, y, sec)
        y -= 26
        for name, desc, price in items:
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.setFont("serifb", 11.5)
            c.drawString(60, y, name)
            wn = stringWidth(name, "serifb", 11.5)
            c.setFont("serif", 11.5)
            c.drawRightString(W - 60, y, price + " ₽")
            wp = stringWidth(price + " ₽", "serif", 11.5)
            dots = "." * int((W - 120 - wn - wp - 16) / stringWidth(".", "serif", 11.5))
            c.setFillColorRGB(0.55, 0.55, 0.55)
            c.drawString(60 + wn + 6, y, dots)
            c.setFillColorRGB(0.35, 0.35, 0.35)
            c.setFont("serif", 9.5)
            # курсив синтезом: наклон текста
            c.saveState()
            c.transform(1, 0, 0.2, 1, 60, y - 14)
            c.drawString(0, 0, desc)
            c.restoreState()
            y -= 36
        y -= 10
    c.setFillColorRGB(0.45, 0.2, 0.05)
    c.setFont("serif", 10)
    c.drawString(60, y - 10, MENU["note"])
    c.save()


def pdf_prose(path):
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A5)
    W, H = A5
    for pg in range(2):
        c.setFont("serif", 8)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawCentredString(W / 2, H - 28, "В. Орлов. Горные тропы")
        y = H - 60
        if pg == 0:
            c.setFillColorRGB(0, 0, 0)
            c.setFont("serifb", 13)
            c.drawCentredString(W / 2, y, PROSE_HEAD)
            y -= 30
        for p in PROSE[pg * 2: pg * 2 + 2]:
            y = _para(c, p, 45, y, W - 90, "serif", 10.5, 14, align="justify", indent=18)
            y -= 2
        c.setFont("serif", 8.5)
        c.setFillColorRGB(0.2, 0.2, 0.2)
        c.drawCentredString(W / 2, 26, str(41 + pg))
        c.showPage()
    c.save()


def pdf_en_guide(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    c.setFont("sansb", 18)
    c.drawString(50, H - 70, EN_GUIDE["title"])
    y = H - 110
    for k, s in enumerate(EN_GUIDE["steps"]):
        c.setFillColorRGB(0.1, 0.3, 0.6)
        c.circle(62, y + 4, 10, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("sansb", 11)
        c.drawCentredString(62, y, str(k + 1))
        y = _para(c, s, 82, y, W - 140, "sans", 11, 15) - 10
    y -= 10
    cw = [150, 120, 120]
    x0 = 50
    for r, row in enumerate(EN_GUIDE["table"]):
        x = x0
        for k, v in enumerate(row):
            if r == 0:
                c.setFillColorRGB(0.1, 0.3, 0.6)
                c.rect(x, y - 6, cw[k], 22, fill=1, stroke=0)
                c.setFillColorRGB(1, 1, 1)
                c.setFont("sansb", 10.5)
            else:
                c.setFillColorRGB(0.1, 0.1, 0.1)
                c.setFont("sans", 10.5)
                c.rect(x, y - 6, cw[k], 22, fill=0, stroke=1)
            c.drawString(x + 6, y, v)
            x += cw[k]
        y -= 22
    c.setFillColorRGB(0.95, 0.85, 0.2)
    c.rect(50, y - 50, W - 100, 32, fill=1, stroke=0)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("sansb", 10.5)
    c.drawString(60, y - 38, EN_GUIDE["warn"])
    c.save()


DE_NOTICE = {
    "title": "Mitteilung an alle Mieterinnen und Mieter",
    "lead": ("Sehr geehrte Damen und Herren, wegen der Erneuerung der Heizungsanlage wird die "
             "Warmwasserversorgung im Gebäude Lindenstraße 14 vorübergehend unterbrochen. "
             "Wir bitten um Ihr Verständnis."),
    "table": [("Datum", "Uhrzeit", "Betroffene Wohnungen"),
              ("Mo., 3. November", "8:00–16:00", "1–12"),
              ("Di., 4. November", "8:00–12:00", "13–24"),
              ("Mi., 5. November", "9:00–18:00", "alle")],
    "note": ("Bei Fragen wenden Sie sich bitte an die Hausverwaltung: "
             "Tel. 030 245 67 80, Montag bis Freitag von 9 bis 17 Uhr."),
    "sign": "Ihre Hausverwaltung Grünwald GmbH",
}

ZH_NOTICE = {
    "title": "停水通知",
    "body": ["因供水管道维修，本小区将于11月8日（星期六）",
             "上午9:00至下午5:00暂停供水。",
             "请各位居民提前做好储水准备。",
             "给您带来的不便，敬请谅解。"],
    "rows": [("受影响楼栋", "1号楼至6号楼"), ("咨询电话", "010-8765 4321")],
    "sign": "阳光花园物业管理处",
    "date": "2026年11月3日",
}


def pdf_de_notice(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    c.setFont("serifb", 17)
    c.drawString(60, H - 80, DE_NOTICE["title"])
    c.setLineWidth(1.2)
    c.line(60, H - 92, W - 60, H - 92)
    y = _para(c, DE_NOTICE["lead"], 60, H - 120, W - 120, "serif", 11, 15, align="justify") - 18
    cw = [160, 120, 195]
    for r, row in enumerate(DE_NOTICE["table"]):
        x = 60
        for k, v in enumerate(row):
            c.setLineWidth(0.6)
            c.rect(x, y - 7, cw[k], 22, fill=0, stroke=1)
            c.setFont("sansb" if r == 0 else "sans", 10.5)
            c.drawString(x + 6, y, v)
            x += cw[k]
        y -= 22
    y = _para(c, DE_NOTICE["note"], 60, y - 24, W - 120, "serif", 11, 15) - 26
    c.setFont("serif", 11)
    c.drawRightString(W - 60, y, DE_NOTICE["sign"])
    c.save()


def png_zh_notice(path):
    from PIL import Image, ImageDraw
    W, H = 900, 1100
    im = Image.new("RGB", (W, H), (252, 250, 244))
    d = ImageDraw.Draw(im)
    d.rectangle((30, 30, W - 30, H - 30), outline=(170, 30, 30), width=4)
    f = _font("cjk", 64)
    tw = d.textlength(ZH_NOTICE["title"], font=f)
    d.text(((W - tw) / 2, 90), ZH_NOTICE["title"], font=f, fill=(180, 20, 20))
    y = 240
    for ln in ZH_NOTICE["body"]:
        d.text((90, y), ln, font=_font("cjk", 32), fill=(30, 30, 30))
        y += 62
    y += 30
    for a, b in ZH_NOTICE["rows"]:
        d.rectangle((90, y - 8, 380, y + 46), outline=(120, 120, 120), width=2)
        d.rectangle((380, y - 8, W - 90, y + 46), outline=(120, 120, 120), width=2)
        d.text((104, y), a, font=_font("cjk", 28), fill=(30, 30, 30))
        d.text((394, y), b, font=_font("cjk", 28), fill=(30, 30, 30))
        y += 54
    fs = _font("cjk", 30)
    for k, t in enumerate((ZH_NOTICE["sign"], ZH_NOTICE["date"])):
        tw = d.textlength(t, font=fs)
        d.text((W - 90 - tw, H - 230 + k * 56), t, font=fs, fill=(30, 30, 30))
    d.ellipse((W - 330, H - 290, W - 150, H - 110), outline=(200, 40, 40), width=5)
    im.save(str(path))


def pdf_cert(path):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    _rl_fonts()
    W, H = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=(W, H))
    c.setStrokeColorRGB(0.7, 0.55, 0.15)
    c.setLineWidth(6)
    c.rect(25, 25, W - 50, H - 50, fill=0, stroke=1)
    c.setLineWidth(1.5)
    c.rect(37, 37, W - 74, H - 74, fill=0, stroke=1)
    c.setFillColorRGB(0.55, 0.4, 0.05)
    c.setFont("serifb", 40)
    c.drawCentredString(W / 2, H - 130, CERT["title"])
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.setFont("serif", 16)
    c.drawCentredString(W / 2, H - 165, CERT["sub"])
    c.setFont("serifb", 24)
    c.drawCentredString(W / 2, H - 235, CERT["name"])
    _para(c, CERT["body"], 150, H - 280, W - 300, "serif", 15, 20, align="center")
    c.setFont("serif", 12)
    c.drawString(90, 90, CERT["date"])
    c.drawRightString(W - 90, 90, CERT["sign"])
    c.save()


# ─── Office / текст ────────────────────────────────────────────────────

def docx_report(path):
    from docx import Document
    from docx.shared import Pt, RGBColor
    d = Document()
    d.sections[0].header.paragraphs[0].text = REPORT_DOCX["header"]
    d.add_heading(REPORT_DOCX["title"], 1)
    for key in ("p1", "p2"):
        p = d.add_paragraph()
        for part in REPORT_DOCX[key]:
            if isinstance(part, tuple):
                r = p.add_run(part[0])
                if part[1] == "b":
                    r.bold = True
                elif part[1] == "i":
                    r.italic = True
                elif part[1] == "red":
                    r.font.color.rgb = RGBColor(0xC0, 0x10, 0x10)
                    r.bold = True
            else:
                p.add_run(part)
    for b in REPORT_DOCX["bullets"]:
        d.add_paragraph(b, style="List Bullet")
    t = d.add_table(rows=0, cols=3)
    t.style = "Table Grid"
    for row in REPORT_DOCX["table"]:
        cells = t.add_row().cells
        for k, v in enumerate(row):
            cells[k].text = v
    p = d.add_paragraph()
    r = p.add_run("* " + REPORT_DOCX["footnote"])
    r.font.size = Pt(8)
    d.sections[0].footer.paragraphs[0].text = "Страница 1"
    d.save(str(path))


def docx_letter(path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    d = Document()
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = LETTER_DOCX["org"] + "\n" + LETTER_DOCX["dept"]
    t.cell(0, 1).text = LETTER_DOCX["to"]
    t.cell(0, 1).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p = d.add_paragraph()
    p.add_run(LETTER_DOCX["subj"]).bold = True
    for k, b in enumerate(LETTER_DOCX["body"]):
        p = d.add_paragraph(b)
        if k == 0:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        else:
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    d.add_paragraph(LETTER_DOCX["sign"])
    d.save(str(path))


def xlsx_budget(path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = "Бюджет I квартал"
    ws.merge_cells("A1:F1")
    ws["A1"] = "Бюджет отдела маркетинга на первый квартал 2027 года"
    ws["A1"].font = Font(bold=True, size=14)
    for r, row in enumerate(BUDGET_XLSX, start=3):
        for k, v in enumerate(row, start=1):
            cell = ws.cell(row=r, column=k)
            if v is None and r > 3:
                cell.value = "=SUM(B%d:D%d)" % (r, r)
            else:
                cell.value = v
            if r == 3:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="2F5597")
                cell.alignment = Alignment(wrap_text=True)
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["F"].width = 40
    ws2 = wb.create_sheet("Примечания")
    ws2["A1"] = "Все суммы указаны в рублях без НДС."
    ws2["A2"] = "Бюджет утверждён на заседании правления 15 декабря."
    wb.save(str(path))


def pptx_slides(path):
    sys.path.append(str(Path(__file__).resolve().parent / "_pylib"))
    extra = Path(__import__("os").environ.get("PPTX_LIB", ""))
    if str(extra):
        sys.path.append(str(extra))
    from pptx import Presentation
    from pptx.util import Pt, Inches
    pr = Presentation()
    for title, bullets in SLIDES:
        s = pr.slides.add_slide(pr.slide_layouts[1])
        s.shapes.title.text = title
        tf = s.placeholders[1].text_frame
        tf.text = bullets[0]
        for b in bullets[1:]:
            tf.add_paragraph().text = b
    s = pr.slides[1]
    tb = s.shapes.add_textbox(Inches(6.2), Inches(5.6), Inches(3.5), Inches(1))
    tb.text_frame.text = "Данные за 9 месяцев 2026 года"
    tb.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
    pr.save(str(path))


def write_text(path, text):
    Path(path).write_text(text, encoding="utf-8")


# ─── картинки ──────────────────────────────────────────────────────────

def _font(k, px):
    from PIL import ImageFont
    return ImageFont.truetype(str(F[k]), int(px))


def png_ui(path):
    from PIL import Image, ImageDraw
    W, H = 1280, 800
    im = Image.new("RGB", (W, H), (245, 247, 250))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 230, H), fill=(32, 41, 64))
    d.text((24, 26), "BANK·ONE", font=_font("sansb", 24), fill=(255, 255, 255))
    for k, m in enumerate(UI_SHOT["menu"]):
        y = 100 + k * 52
        if k == 2:
            d.rectangle((10, y - 10, 220, y + 32), fill=(55, 70, 110))
        d.text((30, y), m, font=_font("sans", 18), fill=(220, 225, 235))
    d.text((270, 30), UI_SHOT["title"], font=_font("sansb", 30), fill=(30, 30, 40))
    d.rounded_rectangle((270, 100, 700, 240), 16, fill=(255, 255, 255), outline=(220, 224, 230))
    d.text((295, 120), UI_SHOT["card"][0], font=_font("sans", 18), fill=(110, 115, 125))
    d.text((295, 155), UI_SHOT["card"][1], font=_font("sansb", 40), fill=(20, 20, 30))
    for k, b in enumerate(UI_SHOT["btn"]):
        x = 740 + k * 220
        col = (37, 99, 235) if k == 0 else (255, 255, 255)
        d.rounded_rectangle((x, 140, x + 200, 196), 10, fill=col, outline=(37, 99, 235))
        f = _font("sansb", 17)
        tw = d.textlength(b, font=f)
        d.text((x + 100 - tw / 2, 157), b, font=f, fill=(255, 255, 255) if k == 0 else (37, 99, 235))
    y = 290
    d.text((270, y), "Последние операции", font=_font("sansb", 20), fill=(30, 30, 40))
    y += 44
    for dt, what, amt in UI_SHOT["rows"]:
        d.line((270, y - 10, 1240, y - 10), fill=(225, 228, 233), width=1)
        d.text((270, y), dt, font=_font("sans", 16), fill=(120, 120, 130))
        d.text((360, y), what, font=_font("sans", 16), fill=(30, 30, 40))
        f = _font("sansb", 16)
        d.text((1240 - d.textlength(amt, font=f), y), amt, font=f,
               fill=(200, 40, 40) if amt.startswith("−") else (20, 140, 60))
        y += 46
    d.text((270, H - 60), UI_SHOT["hint"], font=_font("sans", 13), fill=(130, 135, 145))
    im.save(str(path))


def jpg_poster(path):
    from PIL import Image, ImageDraw
    import numpy as np
    W, H = 1000, 1400
    yy, xx = np.mgrid[0:H, 0:W]
    a = np.stack([200 - yy * 120 / H, 60 + xx * 80 / W, 120 + yy * 100 / H], -1)
    rnd = np.random.default_rng(7)
    a += rnd.normal(0, 6, a.shape)
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    for k in range(9):
        cx, cy, r = rnd.integers(0, W), rnd.integers(500, H), rnd.integers(30, 120)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 200, 80))
    f = _font("sansb", 86)
    words = POSTER["title"].split(" ")
    y = 120
    for w in [" ".join(words[:2]), words[2]]:
        tw = d.textlength(w, font=f)
        d.text(((W - tw) / 2 + 4, y + 4), w, font=f, fill=(40, 10, 40))
        d.text(((W - tw) / 2, y), w, font=f, fill=(255, 255, 255))
        y += 110
    for txt, px, col in [(POSTER["date"], 60, (255, 230, 90)), (POSTER["place"], 44, (255, 255, 255))]:
        f = _font("sansb", px)
        tw = d.textlength(txt, font=f)
        d.text(((W - tw) / 2, y + 30), txt, font=f, fill=col)
        y += px + 40
    f = _font("sans", 30)
    for k, ln in enumerate(["Более 60 кухонь мира, живая музыка", "и мастер-классы для детей"]):
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) / 2, y + 60 + k * 42), ln, font=f, fill=(255, 255, 255))
    d.rounded_rectangle((300, H - 200, 700, H - 120), 40, fill=(230, 40, 90))
    f = _font("sansb", 40)
    tw = d.textlength(POSTER["free"], font=f)
    d.text(((W - tw) / 2, H - 182), POSTER["free"], font=f, fill=(255, 255, 255))
    im.save(str(path), quality=88)


# деградации для трудночитаемых

def _np(im):
    import numpy as np
    return np.asarray(im).astype("float32")


def _img(a):
    import numpy as np
    from PIL import Image
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def _paper(W, H, tone=(236, 226, 200), seed=0, grain=6):
    import numpy as np
    rnd = np.random.default_rng(seed)
    a = np.ones((H, W, 3), "float32") * np.array(tone, "float32")
    low = rnd.normal(0, 1, (H // 40 + 2, W // 40 + 2)).astype("float32")
    import cv2
    low = cv2.resize(low, (W, H), interpolation=cv2.INTER_CUBIC) * 8
    a += low[..., None] + rnd.normal(0, grain, (H, W, 1))
    return a


def _burn(a, seed=0, depth=0.12):
    """Обгоревшие края и прожжённые дыры."""
    import numpy as np
    import cv2
    H, W = a.shape[:2]
    rnd = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    d = np.minimum.reduce([xx, yy, W - 1 - xx, H - 1 - yy]) / min(W, H)
    noise = cv2.resize(rnd.normal(0, 1, (H // 25 + 2, W // 25 + 2)).astype("float32"), (W, H),
                       interpolation=cv2.INTER_CUBIC)
    edge = d + noise * 0.035
    for _ in range(3):
        cx, cy, r = rnd.uniform(0.1, 0.9) * W, rnd.uniform(0.1, 0.9) * H, rnd.uniform(0.012, 0.03) * W
        edge = np.minimum(edge, np.hypot(xx - cx, yy - cy) / min(W, H) - r / min(W, H) + 0.02 + noise * 0.01)
    char = np.clip((depth - edge) / 0.05, 0, 1)
    scorch = np.clip((depth + 0.07 - edge) / 0.07, 0, 1)
    a = a * (1 - 0.55 * scorch[..., None]) + np.array([70, 40, 15], "float32") * 0.55 * scorch[..., None]
    a = a * (1 - char[..., None]) + np.array([18, 12, 8], "float32") * char[..., None]
    return a


def _stains(a, n=5, seed=0, col=(150, 110, 60), alpha=0.35):
    import numpy as np
    import cv2
    H, W = a.shape[:2]
    rnd = np.random.default_rng(seed)
    m = np.zeros((H, W), "float32")
    for _ in range(n):
        cx, cy = int(rnd.uniform(0, W)), int(rnd.uniform(0, H))
        ax, ay = int(rnd.uniform(0.04, 0.12) * W), int(rnd.uniform(0.03, 0.1) * H)
        cv2.ellipse(m, (cx, cy), (ax, ay), rnd.uniform(0, 180), 0, 360, 1.0, -1)
    m = cv2.GaussianBlur(m, (0, 0), W * 0.01)
    ring = cv2.GaussianBlur(np.clip(m * 4 - 2.5, 0, 1), (0, 0), 3)
    k = np.clip(m * alpha + ring * 0.2, 0, 0.7)[..., None]
    return a * (1 - k) + np.array(col, "float32") * k


def _ink(im, lines, font, px, x0, y0, lead, col, jitter=0.0, slant=0.0, seed=0, fade=1.0):
    """Строки «живой» рукой: дрожь базовой линии и кегля."""
    from PIL import ImageDraw
    rnd = random.Random(seed)
    d = ImageDraw.Draw(im)
    y = y0
    for ln in lines:
        x = x0 + rnd.uniform(-jitter, jitter) * px
        for word in ln.split(" "):
            f = _font(font, px * rnd.uniform(1 - jitter * 0.4, 1 + jitter * 0.4))
            dy = rnd.uniform(-jitter, jitter) * px * 0.5
            c = tuple(int(255 - (255 - v) * fade * rnd.uniform(0.75, 1.0)) for v in col)
            d.text((x, y + dy), word, font=f, fill=c)
            x += d.textlength(word + " ", font=f)
        y += lead * rnd.uniform(0.95, 1.05)
    return im


def _skew(im, deg, fill):
    return im.rotate(deg, resample=3, expand=False, fillcolor=fill)


def _perspective(a, k=0.12, seed=0):
    import numpy as np
    import cv2
    H, W = a.shape[:2]
    src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    dst = np.float32([[W * k, H * 0.05], [W * (1 - k * 0.3), 0], [W, H], [0, H * (1 - k * 0.4)]])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(a, M, (W, H), borderMode=cv2.BORDER_REPLICATE)


def _jpeg(im, q):
    from PIL import Image
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return Image.open(io.BytesIO(b.getvalue())).convert("RGB")


def hard_burnt_letter(path):
    from PIL import Image
    W, H = 1100, 1450
    im = _img(_paper(W, H, (226, 205, 160), 1, 7))
    _ink(im, BURNT_LETTER, "hand", 46, 110, 170, 140, (40, 30, 60), jitter=0.12, seed=1, fade=0.85)
    a = _stains(_np(im), 6, 2)
    a = _burn(a, 3, 0.11)
    im = _img(a).filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(1.2))
    _jpeg(im, 55).save(str(path), quality=60)


def hard_handwritten_note(path):
    from PIL import Image, ImageDraw
    W, H = 1000, 1300
    im = _img(_paper(W, H, (250, 250, 244), 4, 3))
    d = ImageDraw.Draw(im)
    for y in range(160, H - 60, 92):
        d.line((40, y + 58, W - 40, y + 58), fill=(170, 195, 230), width=2)
    d.line((110, 0, 110, H), fill=(230, 150, 150), width=2)
    _ink(im, HAND_NOTE, "hand", 46, 140, 168, 92, (20, 40, 140), jitter=0.18, seed=5, fade=0.95)
    im = _skew(im, -3.5, (200, 200, 195))
    _jpeg(im, 62).save(str(path), quality=70)


def hard_prescription(path):
    from PIL import Image, ImageDraw
    W, H = 900, 1200
    im = _img(_paper(W, H, (246, 244, 236), 6, 4))
    d = ImageDraw.Draw(im)
    d.text((60, 50), RX_HEAD[0], font=_font("sansb", 26), fill=(30, 30, 30))
    d.text((60, 92), "ул. Чехова, 8 · тел. 22-14-05", font=_font("sans", 18), fill=(60, 60, 60))
    d.text((W // 2 - 70, 160), RX_HEAD[1], font=_font("sansb", 40), fill=(30, 30, 30))
    d.line((60, 220, W - 60, 220), fill=(80, 80, 80), width=2)
    _ink(im, RX_HAND, "hand", 44, 70, 270, 110, (25, 25, 110), jitter=0.28, seed=7, fade=0.9)
    _ink(im, ["Врач: Петрова"], "hand", 50, 470, 1010, 60, (25, 25, 110), jitter=0.3, seed=8)
    # печать поверх подписи
    a = _np(im)
    import cv2
    import numpy as np
    m = np.zeros(a.shape[:2], "uint8")
    cv2.circle(m, (300, 1040), 95, 255, 6)
    cv2.circle(m, (300, 1040), 70, 255, 3)
    k = (cv2.GaussianBlur(m, (0, 0), 1.2).astype("float32") / 255 * 0.65)[..., None]
    a = a * (1 - k) + np.array([90, 60, 170], "float32") * k
    im = _img(a)
    ImageDraw.Draw(im).text((238, 1030), "ДЛЯ РЕЦЕПТОВ", font=_font("sansb", 18), fill=(110, 85, 180))
    _jpeg(im.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(0.8)), 58).save(str(path), quality=65)


def hard_typewriter_scan(path):
    from PIL import Image
    import numpy as np
    W, H = 1240, 1754
    im = _img(_paper(W, H, (238, 236, 228), 9, 5))
    _ink(im, TYPEWRITER, "mono", 34, 150, 200, 58, (50, 50, 60), jitter=0.04, seed=9, fade=0.72)
    a = _np(im)
    rnd = np.random.default_rng(9)
    a = a * 0.9 + 255 * 0.1  # выцвело
    a += rnd.normal(0, 9, a.shape[:2])[..., None]
    im = _skew(_img(a), 1.8, (225, 223, 215))
    im = _jpeg(im.resize((W // 2, H // 2)).resize((W, H)), 45)
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    c = canvas.Canvas(str(path), pagesize=A4)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=50)
    c.drawImage(ImageReader(io.BytesIO(b.getvalue())), 0, 0, *A4)
    c.save()


def hard_photocopy(path):
    from PIL import Image, ImageDraw
    import numpy as np
    W, H = 900, 640
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((40, 30), PHOTOCOPY["title"], font=_font("sansb", 30), fill=(0, 0, 0))
    y = 100
    xs = [40, 200, 560, W - 40]
    for r, row in enumerate(PHOTOCOPY["rows"]):
        for k, v in enumerate(row):
            d.text((xs[k] + 8, y + 8), v, font=_font("sansb" if r == 0 else "sans", 22), fill=(0, 0, 0))
        d.line((40, y, W - 40, y), fill=(0, 0, 0), width=2)
        y += 48
    d.line((40, y, W - 40, y), fill=(0, 0, 0), width=2)
    for x in xs:
        d.line((x, 100, x, y), fill=(0, 0, 0), width=2)
    d.text((40, y + 30), PHOTOCOPY["note"], font=_font("sans", 20), fill=(0, 0, 0))
    a = _np(im.convert("L"))
    rnd = np.random.default_rng(11)
    a = a * 0.75 + 30 + rnd.normal(0, 30, a.shape)
    a[rnd.random(a.shape) < 0.006] = 0
    import cv2
    a = cv2.GaussianBlur(a, (0, 0), 1.0)
    g = _img(np.stack([a] * 3, -1)).resize((W // 2, H // 2), 2).resize((W, H), 0)
    _jpeg(g, 30).save(str(path), "PNG")


def hard_receipt(path):
    from PIL import Image
    import numpy as np
    import cv2
    W, H = 560, 1150
    im = _img(_paper(W, H, (246, 244, 240), 12, 3))
    _ink(im, RECEIPT, "mono", 23, 30, 60, 62, (60, 60, 75), jitter=0.02, seed=12, fade=0.7)
    a = _np(im)
    rnd = np.random.default_rng(12)
    fold = cv2.GaussianBlur(cv2.resize(rnd.normal(0, 1, (8, 5)).astype("float32"), (W, H), interpolation=cv2.INTER_CUBIC), (0, 0), 25)
    gy, gx = np.gradient(fold)
    shade = 1 + (gx + gy) * 35
    a = a * np.clip(shade, 0.82, 1.08)[..., None]
    a = _perspective(a, 0.1, 12)
    canvas_ = np.ones((1300, 900, 3), "float32") * np.array([60, 55, 50], "float32")
    canvas_[70:70 + H, 170:170 + W] = a
    im = _img(canvas_).rotate(4, resample=3, fillcolor=(60, 55, 50))
    _jpeg(im, 50).save(str(path), quality=60)


def hard_old_newspaper(path):
    from PIL import Image, ImageDraw, ImageOps
    import numpy as np
    W, H = 1200, 1500
    base = _paper(W, H, (214, 196, 150), 13, 8)
    # оборот: зеркальный текст сквозь лист
    back = Image.new("L", (W, H), 255)
    db = ImageDraw.Draw(back)
    rnd = random.Random(13)
    for y in range(120, H - 80, 44):
        db.text((60, y), " ".join(rnd.choice(["объявленіе", "продается", "домъ", "садъ", "лошадь", "контора"])
                                   for _ in range(9)), font=_font("old", 30), fill=0)
    back = ImageOps.mirror(back)
    b = _np(back)[..., None] / 255.0
    base = base * (0.82 + 0.18 * b)
    im = _img(base)
    d = ImageDraw.Draw(im)
    f = _font("oldb", 76)
    tw = d.textlength(OLD_NEWS["title"], font=f)
    d.text(((W - tw) / 2, 50), OLD_NEWS["title"], font=f, fill=(35, 28, 20))
    d.line((60, 160, W - 60, 160), fill=(35, 28, 20), width=4)
    d.line((60, 168, W - 60, 168), fill=(35, 28, 20), width=1)
    colw = (W - 160) // 2
    for k, t in enumerate(OLD_NEWS["cols"]):
        x = 60 + k * (colw + 40)
        y = 200
        words, cur = t.split(), ""
        ff = _font("old", 31)
        for w in words:
            tt = (cur + " " + w).strip()
            if d.textlength(tt, font=ff) > colw:
                d.text((x, y), cur, font=ff, fill=(45, 35, 25))
                y += 44
                cur = w
            else:
                cur = tt
        d.text((x, y), cur, font=ff, fill=(45, 35, 25))
    d.line((W // 2, 200, W // 2, 900), fill=(45, 35, 25), width=2)
    a = _stains(_np(im), 4, 14, (120, 90, 40), 0.25)
    rnd2 = np.random.default_rng(14)
    a += rnd2.normal(0, 10, a.shape[:2])[..., None]
    _jpeg(_img(a), 48).save(str(path), quality=55)


def hard_sign_photo(path):
    from PIL import Image, ImageDraw
    import numpy as np
    W, H = 1400, 1000
    yy, xx = np.mgrid[0:H, 0:W]
    a = np.stack([90 + yy * 0.05, 110 + xx * 0.02, 70 + yy * 0.03], -1).astype("float32")
    a += np.random.default_rng(15).normal(0, 14, a.shape)
    im = _img(a)
    d = ImageDraw.Draw(im)
    d.rectangle((300, 160, 1100, 820), fill=(245, 235, 60))
    d.rectangle((320, 180, 1080, 800), outline=(20, 20, 20), width=8)
    y = 220
    for k, ln in enumerate(SIGN):
        f = _font("sansb", 78 if k in (0, 3) else 48)
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) / 2, y), ln, font=f, fill=(200, 20, 20) if k in (0, 3) else (20, 20, 20))
        y += 120 if k in (0, 3) else 75
    d.rectangle((680, 820, 720, H), fill=(90, 90, 95))
    a = _perspective(_np(im), 0.16, 15)
    # тень от дерева
    import cv2
    m = np.zeros((H, W), "float32")
    for k in range(14):
        cv2.line(m, (int(200 + k * 70), 0), (int(600 + k * 50), H), 1.0, 30)
    m = cv2.GaussianBlur(m, (0, 0), 25)
    a = a * (1 - 0.35 * m[..., None])
    _jpeg(_img(a), 58).save(str(path), quality=62)


def hard_fax(path):
    from PIL import Image, ImageDraw
    import numpy as np
    W, H = 1700, 1100
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)
    d.text((80, 40), "FAX  10/21/26 09:42  CITY LAB  555-0198  P.01", font=_font("mono", 24), fill=0)
    y = 140
    for k, ln in enumerate(FAX):
        d.text((90, y), ln, font=_font("monob" if k == 0 else "mono", 40), fill=0)
        y += 100
    im = im.rotate(-2.6, resample=2, fillcolor=255)
    a = _np(im)
    rnd = np.random.default_rng(16)
    for k in range(6):
        y0 = int(rnd.uniform(0, H))
        a[y0:y0 + int(rnd.uniform(1, 4)), :] *= rnd.uniform(0.2, 0.7)
    a += rnd.normal(0, 40, a.shape)
    small = _img(a).resize((W // 2, H // 2), 2)
    bw = small.point(lambda v: 255 if v > 150 else 0).resize((W, H), 0)
    bw.convert("1").save(str(path))


def hard_water_damaged(path):
    from PIL import Image, ImageFilter
    import numpy as np
    import cv2
    W, H = 1050, 1400
    im = _img(_paper(W, H, (244, 240, 230), 17, 4))
    _ink(im, WATER, "hand", 46, 90, 160, 120, (30, 50, 150), jitter=0.14, seed=17)
    a = _np(im)
    rnd = np.random.default_rng(17)
    m = np.zeros((H, W), "float32")
    for _ in range(4):
        cv2.circle(m, (int(rnd.uniform(0.2, 0.8) * W), int(rnd.uniform(0.15, 0.85) * H)),
                   int(rnd.uniform(90, 170)), 1.0, -1)
    m = cv2.GaussianBlur(m, (0, 0), 35)
    blurred = cv2.GaussianBlur(a, (0, 0), 5)
    tint = blurred * 0.9 + np.array([60, 90, 150], "float32") * 0.1
    k = np.clip(m * 1.2, 0, 0.9)[..., None]
    a = a * (1 - k) + tint * k
    edge = cv2.GaussianBlur(np.clip(m * 6 - 2, 0, 1), (0, 0), 4) - cv2.GaussianBlur(np.clip(m * 6 - 3, 0, 1), (0, 0), 4)
    a -= np.clip(edge, 0, 1)[..., None] * 60
    _jpeg(_img(a), 55).save(str(path), quality=60)


# ─── рецепты ───────────────────────────────────────────────────────────
# fmt — формат выгрузки, который проверяется; kind — что файл трогает.

RECIPES = [
    ("01_newspaper", "pdf", pdf_newspaper, "RU", "EN", "pdf", "3 колонки, буквица, цитата, подпись к фото"),
    ("02_article", "pdf", pdf_article, "RU", "EN", "pdf", "статья: реферат в рамке, 2 колонки, формулы, индексы, литература"),
    ("03_invoice", "pdf", pdf_invoice, "RU", "UZ", "pdf", "счёт: таблица с линиями, цифры вправо, логотип, печать"),
    ("04_infographic", "pdf", pdf_infographic, "RU", "EN", "pdf", "белый текст на цветных плашках, стрелки, значок"),
    ("05_verse", "pdf", pdf_verse, "RU", "EN", "pdf", "стихи, заголовок вразрядку, эпиграф справа (Ч6)"),
    ("06_brochure", "pdf", pdf_brochure, "RU", "DE", "pdf", "буклет альбомный, повёрнутый текст 90° и 15°"),
    ("07_form", "pdf", pdf_form, "RU", "EN", "pdf", "бланк: подписи полей, линии, флажки"),
    ("08_menu", "pdf", pdf_menu, "RU", "EN", "pdf", "меню: отточия, цены, наклонный текст, цветной фон"),
    ("09_prose", "pdf", pdf_prose, "RU", "UZ", "pdf", "книга 2 стр.: выключка, красная строка, колонтитул, номер"),
    ("10_en_guide_zh", "pdf", pdf_en_guide, "EN", "ZH", "pdf", "EN→ZH: шаги с кружками, таблица, плашка"),
    ("11_cert_ar", "pdf", pdf_cert, "RU", "AR", "pdf", "сертификат RU→AR: письмо справа налево, рамка"),
    ("12_report", "docx", docx_report, "RU", "EN", "docx_layout", "Word: жирный/курсив/цвет внутри абзаца, таблица, список, колонтитул"),
    ("13_letter", "docx", docx_letter, "RU", "UZ-CYRL", "docx_layout", "Word: письмо, таблица-шапка, выключка"),
    ("14_budget", "xlsx", xlsx_budget, "RU", "EN", "original", "Excel: объединённые ячейки, формулы, два листа"),
    ("15_slides", "pptx", pptx_slides, "RU", "EN", "original", "PowerPoint: 3 слайда, надпись"),
    ("16_html", "html", lambda p: write_text(p, HTML_EN), "EN", "RU", "original", "HTML: инлайн-теги, список, таблица"),
    ("17_md", "md", lambda p: write_text(p, MD_RU), "RU", "EN", "original", "Markdown: заголовки, списки, код, цитата"),
    ("18_subs", "srt", lambda p: write_text(p, SRT_RU), "RU", "EN", "original", "субтитры .srt"),
    ("19_ui", "png", png_ui, "RU", "EN", "original", "скриншот интерфейса: мелкий текст, кнопки, цвета"),
    ("20_poster", "jpg", jpg_poster, "RU", "EN", "original", "афиша: крупный текст с тенью на градиенте"),
    ("21_burnt_letter", "jpg", hard_burnt_letter, "RU", "EN", "original", "ТРУДНО: обгоревшее письмо от руки, пятна"),
    ("22_hand_note", "jpg", hard_handwritten_note, "RU", "EN", "original", "ТРУДНО: записка от руки на линованной бумаге, наклон"),
    ("23_prescription", "jpg", hard_prescription, "RU", "EN", "original", "ТРУДНО: рецепт — печатная шапка и неразборчивая рука, печать"),
    ("24_typewriter_scan", "pdf", hard_typewriter_scan, "RU", "DE", "pdf", "ТРУДНО: выцветший машинописный скан, перекос"),
    ("25_photocopy", "png", hard_photocopy, "RU", "EN", "original", "ТРУДНО: ксерокопия низкого разрешения, таблица, шум"),
    ("26_receipt", "jpg", hard_receipt, "RU", "UZ", "original", "ТРУДНО: мятый выцветший чек под углом"),
    ("27_old_newspaper", "jpg", hard_old_newspaper, "RU", "EN", "original", "ТРУДНО: старая газета, дореформенная орфография, оборот насквозь"),
    ("28_sign_photo", "jpg", hard_sign_photo, "RU", "EN", "original", "ТРУДНО: табличка под углом, тени"),
    ("29_fax", "png", hard_fax, "EN", "RU", "original", "ТРУДНО: факс 1 бит, перекос, полосы"),
    ("30_water", "jpg", hard_water_damaged, "RU", "EN", "original", "ТРУДНО: страница залита водой, расплывшиеся чернила"),
    ("31_de_notice", "pdf", pdf_de_notice, "DE", "RU", "pdf", "DE→: уведомление, таблица, составные слова, ß/умлауты"),
    ("32_zh_notice", "png", png_zh_notice, "ZH", "RU", "original", "ZH→: объявление-картинка, иероглифы, таблица, печать"),
]


# Языковая матрица: частые в СНГ пары на тех же файлах. Один файл — разные
# письменности и длины перевода (кириллица ↔ латиница, иероглифы, справа
# налево, длинные немецкие слова). `python tools/corpus_build.py OUT --langs`.
LANG_MATRIX = [
    ("02_article", "RU", "DE"), ("02_article", "RU", "ZH"),
    ("03_invoice", "RU", "EN"), ("03_invoice", "RU", "KK"), ("03_invoice", "RU", "TR"),
    ("04_infographic", "RU", "UZ-CYRL"), ("04_infographic", "RU", "AR"), ("04_infographic", "RU", "KO"),
    ("08_menu", "RU", "ZH"), ("08_menu", "RU", "KY"),
    ("09_prose", "RU", "TG"), ("09_prose", "RU", "AZ"), ("09_prose", "RU", "UK"),
    ("12_report", "RU", "DE"), ("12_report", "RU", "KK"),
    ("15_slides", "RU", "ZH"),
    ("19_ui", "RU", "DE"), ("19_ui", "RU", "ZH"), ("19_ui", "RU", "KK"),
    ("20_poster", "RU", "TR"), ("20_poster", "RU", "FR"),
    ("24_typewriter_scan", "RU", "EN"),
    ("10_en_guide_zh", "EN", "RU"), ("10_en_guide_zh", "EN", "UZ"),
    ("31_de_notice", "DE", "RU"), ("31_de_notice", "DE", "EN"),
    ("32_zh_notice", "ZH", "RU"), ("32_zh_notice", "ZH", "EN"),
]


def main_langs(out: Path):
    import shutil
    base = {r[0]: r for r in RECIPES}
    tmp = out / "_base"
    tmp.mkdir(parents=True, exist_ok=True)
    manifest = []
    for rid, src, tgt in LANG_MATRIX:
        _r, ext, fn, _s, _t, fmt, what = base[rid]
        bp = tmp / ("%s.%s" % (rid, ext))
        if not bp.exists():
            random.seed(rid)
            fn(bp)
        lid = "L%s_%s" % (rid, tgt.lower().replace("-", ""))
        shutil.copyfile(bp, out / ("%s.%s" % (lid, ext)))
        manifest.append({"id": lid, "file": "%s.%s" % (lid, ext), "src": src, "tgt": tgt, "export": fmt,
                         "hard": what.startswith("ТРУДНО"), "what": "%s → %s: %s" % (src, tgt, what)})
    shutil.rmtree(tmp)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("матрица:", len(manifest), "файлов")


def main(argv):
    out = Path(argv[1])
    if "--langs" in argv:
        out.mkdir(parents=True, exist_ok=True)
        return main_langs(out)
    out.mkdir(parents=True, exist_ok=True)
    only = None
    if "--only" in argv:
        only = set(argv[argv.index("--only") + 1].split(","))
    manifest = []
    recipes = RECIPES
    if "--set2" in argv:
        # Второй корпус (41–70): сложная вёрстка, языки, офисные форматы, трудные фото.
        import corpus2_a, corpus2_b, corpus2_c
        recipes = corpus2_a.RECIPES + corpus2_b.RECIPES + corpus2_c.RECIPES
    for rid, ext, fn, src, tgt, fmt, what in recipes:
        path = out / ("%s.%s" % (rid, ext))
        if only is None or rid in only:
            random.seed(rid)
            fn(path)
            print("ok", path.name, path.stat().st_size // 1024, "КБ")
        manifest.append({"id": rid, "file": path.name, "src": src, "tgt": tgt, "export": fmt,
                         "hard": what.startswith("ТРУДНО"), "what": what})
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
