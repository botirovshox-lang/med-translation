# -*- coding: utf-8 -*-
"""Маленькая «книга» PDF с дефектами боевой (Лазебный, «Пчелиная аптека»)
для тестов разбора текстового слоя: `tests/test_pdf_layout.py`,
`tests/test_resegment.py`. Не тест — имя без `test_`.

PDF собирается руками (без reportlab): шрифт Helvetica с картой ToUnicode —
pypdf достаёт текст по карте, глифы ему не нужны. Порядок строк в потоке
повторяет боевую книгу: врезка и эпиграф стоят не там, где их видно.
"""
import io


# ─── Сборщик PDF ─────────────────────────────────────────────────────


def make_pdf(pages: list, size=(400, 600)) -> bytes:
    """pages: [[("t", x, y, кегль, текст) | ("re", x, y, w, h) | ("img", x, y, w, h)], …]
    — операции в ПОРЯДКЕ ПОТОКА. Текст — однобайтовыми кодами по карте ToUnicode."""
    chars = sorted({c for p in pages for op in p if op[0] == "t" for c in op[4]} - {" "})
    assert len(chars) < 220, "слишком много разных знаков для однобайтовой карты"
    code = {" ": 0x20}
    nxt = 0x21
    for c in chars:
        if nxt == 0x20:
            nxt += 1
        code[c] = nxt
        nxt += 1
    objs: list = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    bf = []
    items = [(v, c) for c, v in code.items()]
    for k in range(0, len(items), 100):
        chunk = items[k:k + 100]
        bf.append(("%d beginbfchar\n" % len(chunk)
                   + "".join("<%02X> <%04X>\n" % (v, ord(c)) for v, c in chunk)
                   + "endbfchar\n"))
    cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
            "1 begincodespacerange\n<00> <FF>\nendcodespacerange\n" + "".join(bf)
            + "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n").encode()
    tu = add(b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream")
    widths = " ".join(["500"] * 224)
    font = add(("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /FirstChar 32 /LastChar 255 "
                "/Widths [%s] /ToUnicode %d 0 R >>" % (widths, tu)).encode())
    img = add(b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
              b"/BitsPerComponent 8 /Length 1 >>\nstream\n\x80\nendstream")
    page_ids = []
    pages_id_placeholder = len(objs) + 1 + 2 * len(pages)
    for p in pages:
        ops = []
        for op in p:
            if op[0] == "t":
                _t, x, y, s, text = op
                hexs = "".join("%02X" % code[c] for c in text)
                ops.append("BT /F1 %g Tf 1 0 0 1 %g %g Tm <%s> Tj ET" % (s, x, y, hexs))
            elif op[0] == "re":
                ops.append("%g %g %g %g re S" % op[1:])
            elif op[0] == "img":
                _i, x, y, w, h = op
                ops.append("q %g 0 0 %g %g %g cm /Im1 Do Q" % (w, h, x, y))
        stream = "\n".join(ops).encode("latin-1")
        cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        pid = add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                   "/Resources << /Font << /F1 %d 0 R >> /XObject << /Im1 %d 0 R >> >> >>"
                   % (pages_id_placeholder, size[0], size[1], cid, font, img)).encode())
        page_ids.append(pid)
    pages_id = add(("<< /Type /Pages /Kids [%s] /Count %d >>"
                    % (" ".join("%d 0 R" % i for i in page_ids), len(page_ids))).encode())
    assert pages_id == pages_id_placeholder
    cat = add(("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode())
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offs = []
    for i, body in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offs:
        out.write(b"%010d 00000 n \n" % o)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref))
    return out.getvalue()


# ─── Книга в восемь страниц ──────────────────────────────────────────
HEAD_A = "Лекарство из улья"
HEAD_B1, HEAD_B2 = "Апитоксинотерапия —", "лечение пчелоужалением"
_ENDS = ["от силы семьи и взятка.", "от места и времени года.", "от ухода за ульями.",
         "от лета и от осени.", "от пасечника и его опыта.", "от погоды в мае и июне."]


def fill(k):
    """Абзац-наполнитель; последняя строка у каждой страницы своя — одинаковая
    последняя строка на многих страницах выглядела бы нижним колонтитулом."""
    return ["Сбор прополиса следует прекращать за шестьдесят дней до на­",
            "ступления первых заморозков. Гнездо пчел без прополиса на",
            "зиму оставлять нельзя, количество прополиса зависит от по­",
            "годы, растительности и породы пчел, " + _ENDS[k % len(_ENDS)]]


def body(lines, top=520, x=40, lead=12, first_indent=16):
    """Абзац: первая строка с отступом, дальше от поля."""
    return [("t", x + (first_indent if k == 0 else 0), top - k * lead, 10, t) for k, t in enumerate(lines)]


def head_a(text=HEAD_A):
    return [("t", 40, 560, 11, text)]


def head_b(first=HEAD_B1):
    return [("t", 250, 560, 11, first), ("t", 240, 548, 11, HEAD_B2)]


def folio(n):
    return [("t", 300, 40, 10.5, str(n))]


p0 = (head_a()
      + body(fill(0) + ["Прополис должен иметь плотную, в изломе неоднородную",
                     "структуру и вязкую при 20-40 °С, твердую — ниже 20 °С кон-"], top=520)
      # Врезка внизу страницы — в потоке ПОСЛЕ текста, заголовок и рамка — после неё.
      + [("re", 60, 250, 260, 130)]
      + [("t", 86, 345, 10, "В продаже на рынках, как правило, покупате­"),
         ("t", 70, 333, 10, "лю предлагают прополис с добавкой воска. Это"),
         ("t", 70, 321, 10, "объясняется высокой стоимостью чистого пропо­"),
         ("t", 70, 309, 10, "лиса. Добавку видно по более светлому цвету.")]
      + [("t", 150, 365, 9.5, "На заметку"), ("t", 230, 372, 12, "---— хххх")]
      + folio(77))
p1 = (head_a("Лекарство из улъя")          # колонтитул распознан с ошибкой
      + body(["систенцию, массовую долю воска не более 25 %, массовую долю",
              "флавоноидных и других фенольных соединений, йодное число",
              "в домашних условиях определить невозможно, это делают",
              "в лаборатории по утвержденной методике испытаний."], top=520, first_indent=0)
      + body(fill(1), top=460) + folio(78))
p2 = (head_b()
      + body(fill(2), top=520)
      + body(["Показания к возможному использованию пчелоужалений:",
              "боли в правом подреберье; желудочно-кишечные расстрой-"], top=460)
      + folio(79))
p3 = (head_b("Апцтоксинотерапия —")        # колонтитул с ошибкой распознавания
      + [("img", 100, 330, 160, 190)]
      + [("t", 265, 500, 8.5, "НК4"), ("t", 265, 360, 8.5, "НК1"), ("t", 160, 305, 10, "Рис. 7")]
      + body(["ства, частая тошнота со рвотой; недержание мочи, затруднен­",
              "ное мочеиспускание; конъюнктивит; межреберная невралгия;",
              "боли при грыже и в пояснице, особенно после нагрузки."], top=275, first_indent=0)
      + folio(80))
tail_lines = body(["Из сокровищницы народной медицины взято немало вы-"], top=250)
p4 = (head_a()
      + body(["Хранить прополис можно в ящичках в затемненных помещени­",
              "ях при температуре не выше 25 °С или прямо в холодильнике."], top=520)
      + tail_lines
      + [("t", 40, 226, 10, "ди них определенное место занимает пчелиный яд — апиток-"),
         ("t", 40, 214, 10, "син (от латинского Apis — пчела и греческого toxikon — яд).")]
      # Заголовок, эпиграф, подпись и пропущенная строка — В КОНЦЕ потока.
      + [("t", 150, 440, 18, "Пчелиный яд")]
      + [("t", 215, 410, 8.5, "Все, что нас окружает, — в опреде­"),
         ("t", 200, 399, 8.5, "ленной степени яд, в природе неядови­"),
         ("t", 200, 388, 8.5, "того нет ничего. И только от количества"),
         ("t", 200, 377, 8.5, "зависит, станет ли какое-то вещество"),
         ("t", 200, 366, 8.5, "для нас ядом или нет."),
         ("t", 300, 350, 8.5, "Авиценна")]
      + [("t", 40, 238, 10, "сокоэффективных лечебно-профилактических средств. Сре-")]
      + folio(81))
p5 = head_b() + body(fill(3), top=520) + folio(82)
p6 = head_a() + body(fill(4), top=520) + folio(83)
p7 = head_b() + body(fill(5), top=520) + folio(84)
PDF = make_pdf([p0, p1, p2, p3, p4, p5, p6, p7])
