import sys, random, math; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_build import F, _rl_fonts, _wrap, _para, _font, _np, _img, _paper, _jpeg

"""Корпус, часть 2б: файлы 51–60 (вертикальный японский, арабское письмо в Word,
корейская анкета, EN→HI, испанский буклет, PowerPoint с диаграммой, многолистовой
Excel, сложный Word, вложенный HTML, турецкое уведомление). Весь текст написан
для корпуса, организации и имена вымышлены."""

FONTS = Path(F["sans"]).parent
FJ = FONTS / "NotoSansJP-Regular.otf"
FK = FONTS / "NotoSansKR-Regular.otf"


def _pf(path, px):
    from PIL import ImageFont
    return ImageFont.truetype(str(path), int(px))


# ─── 51: японское объявление, вертикальный набор ───────────────────────

JA = {
    "title": "断水のお知らせ",
    "sub": "緑川市上下水道局",
    "cols": [
        "平素より水道事業にご理解とご協力をいただき、誠にありがとうございます。このたび、老朽化した"
        "配水管の取替工事のため、下記の日程で断水を行います。",
        "断水中は水道が使えませんので、前日までに飲み水の準備をお願いいたします。工事の進み具合により、"
        "時間が前後する場合があります。",
        "断水の解除後、しばらく水が白く濁ることがありますが、「空気」によるものです。数分間水を流して"
        "いただければ問題ありません。",
        "ご不便をおかけしますが、ご理解のほどよろしくお願い申し上げます。",
    ],
    "head": ("日付", "時間", "対象地域"),
    "rows": [("11月12日（木）", "9:00～16:00", "桜台一丁目～三丁目"),
             ("11月13日（金）", "9:00～15:00", "東町二丁目・若葉町")],
    "contact": ["お問い合わせ：緑川市上下水道局 工務課 給水係", "電話 0544-27-3810（平日 8:30～17:15）"],
    "stamp": "水道局",
}

# вертикальные формы знаков: что заменить, что повернуть, что сдвинуть
_JA_VERT = {}
_JA_ROT = set("ー～-…「」（）『』")
_JA_PUNCT = set("、。")
_JA_SMALL = set("ゃゅょっぁぃぅぇぉャュョッァィゥェォ")


def png_ja_vertical(path):
    from PIL import Image, ImageDraw
    W, H = 1100, 1500
    im = Image.new("RGB", (W, H), (251, 249, 243))
    d = ImageDraw.Draw(im)
    d.rectangle((24, 24, W - 24, H - 24), outline=(40, 70, 120), width=3)
    d.rectangle((34, 34, W - 34, H - 34), outline=(40, 70, 120), width=1)
    # горизонтальный заголовок
    ft = _pf(FJ, 76)
    tw = d.textlength(JA["title"], font=ft)
    d.text(((W - tw) / 2, 70), JA["title"], font=ft, fill=(20, 40, 90))
    fs = _pf(FJ, 30)
    sw = d.textlength(JA["sub"], font=fs)
    d.text(((W - sw) / 2, 175), JA["sub"], font=fs, fill=(60, 60, 60))
    d.line((90, 230, W - 90, 230), fill=(40, 70, 120), width=2)
    # вертикальные колонки справа налево
    px, cell, colw = 34, 38, 60
    top, bottom = 262, 1022
    per = (bottom - top) // cell
    f = _pf(FJ, px)
    x = W - 110
    for text in JA["cols"]:
        text = "　" + text                      # отступ абзаца — пустая клетка
        chunks = [text[i:i + per] for i in range(0, len(text), per)]
        # кинсоку: знак препинания не начинает колонку
        for k in range(1, len(chunks)):
            while chunks[k] and chunks[k][0] in "、。」）ー":
                chunks[k - 1] += chunks[k][0]
                chunks[k] = chunks[k][1:]
        for ch_line in chunks:
            y = top
            for ch in ch_line:
                g = _JA_VERT.get(ch, ch)
                if ch in _JA_ROT:
                    tile = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
                    ImageDraw.Draw(tile).text((cell / 2, cell / 2), ch, font=f, fill=(25, 25, 25), anchor="mm")
                    tile = tile.rotate(-90)
                    im.paste(tile, (int(x - cell / 2), int(y)), tile)
                else:
                    dx = dy = 0
                    if ch in _JA_SMALL:
                        dx, dy = px * 0.12, -px * 0.1
                    elif ch in _JA_PUNCT:
                        dx, dy = px * 0.55, -px * 0.55     # вертикальная запятая — в правом верхнем углу
                    d.text((x + dx, y + cell / 2 + dy), g, font=f, fill=(25, 25, 25), anchor="mm")
                y += cell
            x -= colw
    # горизонтальная таблица внизу
    ty = 1060
    cw = [250, 230, 440]
    x0 = (W - sum(cw)) / 2
    fh = _pf(FJ, 28)
    for r, row in enumerate([JA["head"]] + JA["rows"]):
        xx = x0
        for k, v in enumerate(row):
            fill = (220, 230, 245) if r == 0 else None
            d.rectangle((xx, ty, xx + cw[k], ty + 58), outline=(60, 80, 120), width=2, fill=fill)
            d.text((xx + cw[k] / 2, ty + 29), v, font=fh, fill=(20, 20, 20), anchor="mm")
            xx += cw[k]
        ty += 58
    fc = _pf(FJ, 24)
    for k, ln in enumerate(JA["contact"] + ["令和8年10月20日"]):
        d.text((90, ty + 36 + k * 38), ln, font=fc, fill=(40, 40, 40))
    # красная печать ханко
    cx, cy, r = W - 170, H - 150, 70
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(200, 30, 30), width=6)
    d.ellipse((cx - r + 10, cy - r + 10, cx + r - 10, cy + r - 10), outline=(200, 30, 30), width=2)
    fz = _pf(FJ, 33)
    for k, ch in enumerate(JA["stamp"]):
        d.text((cx, cy - 36 + k * 36), ch, font=fz, fill=(200, 30, 30), anchor="mm")
    a = _np(im)
    import numpy as np
    a += np.random.default_rng(51).normal(0, 2.5, a.shape)
    _img(a).save(str(path))


# ─── 52: арабское официальное письмо (Word, справа налево) ─────────────

AR = {
    "org": "الهيئة العامة للمكتبات",
    "dept": "إدارة الخدمات الثقافية – مدينة النخيل",
    "num": "الرقم: ٢٠٢٦/٤٨٧",
    "date": "التاريخ: ١٥ جمادى الأولى ١٤٤٨ هـ الموافق ٢٧ أكتوبر ٢٠٢٦ م",
    "to": "السيد/ مدير مدرسة الأمل الثانوية المحترم",
    "greet": "تحية طيبة وبعد،",
    "subj": "الموضوع: برنامج الزيارات المدرسية إلى المكتبة المركزية للعام الدراسي ٢٠٢٦–٢٠٢٧",
    "body": [
        "يسرّ الهيئة العامة للمكتبات أن تدعو طلاب مدرستكم الكريمة إلى المشاركة في برنامج الزيارات "
        "المدرسية الذي تنظّمه المكتبة المركزية خلال الفصل الدراسي الأول. ويهدف البرنامج إلى تعريف "
        "الطلاب بمصادر المعرفة الحديثة، وتدريبهم على استخدام الفهارس الإلكترونية، وتشجيعهم على "
        "القراءة والبحث العلمي.",
        "وقد أعددنا جدولاً بالمواعيد المتاحة وعدد المقاعد في كل زيارة، ونرجو التكرّم بتحديد الموعد "
        "المناسب لكم وإبلاغنا به في موعد أقصاه ٢٠ نوفمبر ٢٠٢٦.",
    ],
    "table": [
        ("الزيارة", "التاريخ", "الوقت", "عدد الطلاب", "الرسوم (ريال)"),
        ("الأولى", "10/12/2026", "9:00 – 11:00", "35", "0"),
        ("الثانية", "17/12/2026", "10:00 – 12:00", "40", "0"),
        ("الثالثة", "07/01/2027", "9:30 – 11:30", "30", "150"),
        ("الرابعة", "14/01/2027", "11:00 – 13:00", "25", "150"),
    ],
    "after": [
        "علماً بأن المكتبة توفّر وسيلة نقل مجانية للمدارس التي تبعد أكثر من ١٥ كيلومتراً عن مقرّها، "
        "وتُخصَّص الرسوم المذكورة لورشة الطباعة ثلاثية الأبعاد فقط.",
        "وللاستفسار يُرجى التواصل مع قسم الأنشطة على الرقم 011 456 7890 أو عبر البريد الإلكتروني "
        "activities@nakheel-lib.example.",
        "وتفضّلوا بقبول فائق الاحترام والتقدير،",
    ],
    "sign": ["مدير إدارة الخدمات الثقافية", "د. سلمى عبد الرحمن الحربي", "(التوقيع)"],
}


def _put(parent, el, successors):
    """Вставить элемент OOXML перед первым из «последующих» по схеме (порядок важен для Word)."""
    from docx.oxml.ns import qn
    for tag in successors:
        x = parent.find(qn("w:" + tag))
        if x is not None:
            x.addprevious(el)
            return el
    parent.append(el)
    return el


_PPR_AFTER_BIDI = ("adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
                   "suppressOverlap", "jc", "textDirection", "textAlignment", "textboxTightWrap",
                   "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")
_SECT_AFTER_COLS = ("formProt", "vAlign", "noEndnote", "titlePg", "textDirection", "bidi", "rtlGutter",
                    "docGrid", "printerSettings", "sectPrChange")
_SECT_AFTER_BIDI = ("rtlGutter", "docGrid", "printerSettings", "sectPrChange")


def _rtl_par(p, size=None, bold=False, font="Noto Naskh Arabic"):
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls, qn
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    pPr = p._p.get_or_add_pPr()
    _put(pPr, parse_xml("<w:bidi %s/>" % nsdecls("w")), _PPR_AFTER_BIDI)
    for r in p.runs:
        rPr = r._r.get_or_add_rPr()
        rf = rPr.find(qn("w:rFonts"))
        if rf is None:
            rf = parse_xml("<w:rFonts %s/>" % nsdecls("w"))
            rPr.insert(0, rf)
        rf.set(qn("w:cs"), font)
        rf.set(qn("w:ascii"), font)
        rf.set(qn("w:hAnsi"), font)
        if bold:
            r.bold = True
            rPr.append(parse_xml("<w:bCs %s/>" % nsdecls("w")))
        if size:
            rPr.append(parse_xml('<w:szCs %s w:val="%d"/>' % (nsdecls("w"), size * 2)))
            from docx.shared import Pt
            r.font.size = Pt(size)
        rPr.append(parse_xml("<w:rtl %s/>" % nsdecls("w")))
    if p.alignment is None:
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    return p


def docx_ar_letter(path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    from docx.shared import Pt
    d = Document()
    sec = d.sections[0]
    _put(sec._sectPr, parse_xml("<w:bidi %s/>" % nsdecls("w")), _SECT_AFTER_BIDI)
    hp = sec.header.paragraphs[0]
    hp.text = AR["org"] + " — " + AR["dept"]
    _rtl_par(hp, 10)
    for t, sz, b in ((AR["org"], 16, True), (AR["dept"], 12, False)):
        p = d.add_paragraph(t)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _rtl_par(p, sz, b)
    for t in (AR["num"], AR["date"]):
        p = d.add_paragraph(t)
        _rtl_par(p, 11)
    for t in (AR["to"], AR["greet"]):
        _rtl_par(d.add_paragraph(t), 12, t == AR["to"])
    p = d.add_paragraph(AR["subj"])
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _rtl_par(p, 13, True)
    for t in AR["body"]:
        p = d.add_paragraph(t)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _rtl_par(p, 12)
    tb = d.add_table(rows=0, cols=5)
    tb.style = "Table Grid"
    _put(tb._tbl.tblPr, parse_xml("<w:bidiVisual %s/>" % nsdecls("w")),
         ("tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook"))
    for r, row in enumerate(AR["table"]):
        cells = tb.add_row().cells
        for k, v in enumerate(row):
            cells[k].text = v
            cp = cells[k].paragraphs[0]
            cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _rtl_par(cp, 11, r == 0)
    for k, t in enumerate(AR["after"]):
        p = d.add_paragraph(t)
        if k == 0:
            p.paragraph_format.space_before = Pt(10)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _rtl_par(p, 12)
    for k, t in enumerate(AR["sign"]):
        p = d.add_paragraph(t)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT         # в абзаце w:bidi Word читает right как «конец» — подпись слева
        _rtl_par(p, 12, k == 1)
        p.paragraph_format.space_after = Pt(0)
    fp = sec.footer.paragraphs[0]
    fp.text = "ص.ب ٤٤١٢ – مدينة النخيل – هاتف 011 456 7000"
    _rtl_par(fp, 9)
    d.save(str(path))


# ─── 53: корейская анкета-картинка ──────────────────────────────────────

KO = {
    "org": "한빛문화재단",
    "title": "2027학년도 장학금 신청서",
    "note": "※ 굵은 테두리 안의 항목은 모두 빠짐없이 작성해 주십시오. 기재 내용이 사실과 다를 경우 선발이 취소될 수 있습니다.",
    "fields": [("성명", "김서연"), ("생년월일", "2006년 3월 14일"), ("연락처", "010-4821-7735"),
               ("이메일", "seoyeon.kim@hanbit-mail.example"), ("주소", "대전광역시 유성구 노은동로 118, 302동 1204호"),
               ("소속 학교", "한빛대학교"), ("학과 / 학년", "생명공학과 / 2학년")],
    "kind": ("신청 구분", ["신규", "계속"], 0),
    "income": ("가구 소득 구간", ["1~3구간", "4~6구간", "7~8구간", "9구간 이상"], 1),
    "docs": ("제출 서류", ["재학증명서", "성적증명서", "가족관계증명서", "소득금액증명원"], {0, 1, 3}),
    "consent": "개인정보 수집·이용 동의: 재단은 장학생 선발을 위하여 위 개인정보를 수집하며, 선발 종료 후 1년간 보관합니다. 신청인은 동의를 거부할 권리가 있으나, 동의하지 않을 경우 장학생 선발 대상에서 제외됩니다.",
    "agree": ["동의함", "동의하지 않음"],
    "date": "2026년 11월     일",
    "sign": ("신청인", "(서명 또는 인)"),
    "foot": "한빛문화재단 이사장 귀하  |  문의: 장학사업팀 042-610-5523",
}


def png_ko_form(path):
    from PIL import Image, ImageDraw
    W, H = 1240, 1700
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    # шапка-полоса с логотипом
    d.rectangle((0, 0, W, 130), fill=(22, 84, 140))
    d.ellipse((50, 25, 130, 105), fill=(255, 255, 255))
    d.ellipse((66, 41, 114, 89), fill=(245, 170, 40))
    d.text((150, 38), KO["org"], font=_pf(FK, 44), fill=(255, 255, 255))
    d.text((W - 60, 65), "HANBIT CULTURAL FOUNDATION", font=_font("sansb", 20), fill=(200, 220, 240), anchor="rm")
    ft = _pf(FK, 52)
    d.text((W / 2, 200), KO["title"], font=ft, fill=(20, 20, 20), anchor="mm")
    fn = _pf(FK, 21)
    y = 250
    for ln in _wrap_px(d, KO["note"], fn, W - 140):
        d.text((70, y), ln, font=fn, fill=(170, 40, 40))
        y += 30
    y += 15
    x0, x1, lw = 60, W - 60, 230
    fl, fv = _pf(FK, 27), _pf(FK, 27)
    top = y
    for lab, val in KO["fields"]:
        d.rectangle((x0, y, x0 + lw, y + 66), fill=(234, 240, 248), outline=(80, 80, 80), width=1)
        d.rectangle((x0 + lw, y, x1, y + 66), outline=(80, 80, 80), width=1)
        d.text((x0 + lw / 2, y + 33), lab, font=fl, fill=(30, 30, 30), anchor="mm")
        d.text((x0 + lw + 22, y + 33), val, font=fv, fill=(20, 40, 120), anchor="lm")
        y += 66
    d.rectangle((x0, top, x1, y), outline=(0, 0, 0), width=4)
    y += 30

    def boxrow(y, lab, opts, chosen):
        d.rectangle((x0, y, x0 + lw, y + 70), fill=(234, 240, 248), outline=(80, 80, 80), width=1)
        d.rectangle((x0 + lw, y, x1, y + 70), outline=(80, 80, 80), width=1)
        d.text((x0 + lw / 2, y + 35), lab, font=fl, fill=(30, 30, 30), anchor="mm")
        x = x0 + lw + 24
        for k, o in enumerate(opts):
            d.rectangle((x, y + 22, x + 26, y + 48), outline=(30, 30, 30), width=2)
            on = chosen == k if isinstance(chosen, int) else k in chosen
            if on:
                d.line((x + 4, y + 35, x + 11, y + 44), fill=(20, 40, 120), width=4)
                d.line((x + 11, y + 44, x + 24, y + 22), fill=(20, 40, 120), width=4)
            d.text((x + 36, y + 35), o, font=_pf(FK, 25), fill=(30, 30, 30), anchor="lm")
            x += 60 + d.textlength(o, font=_pf(FK, 25))
        return y + 70

    for lab, opts, ch in (KO["kind"], KO["income"], KO["docs"]):
        y = boxrow(y, lab, opts, ch)
    y += 30
    d.rectangle((x0, y, x1, y + 170), outline=(80, 80, 80), width=1, fill=(250, 250, 246))
    yy = y + 18
    for ln in _wrap_px(d, KO["consent"], _pf(FK, 23), x1 - x0 - 40):
        d.text((x0 + 20, yy), ln, font=_pf(FK, 23), fill=(40, 40, 40))
        yy += 34
    xx = x1 - 420
    for k, o in enumerate(KO["agree"]):
        d.rectangle((xx, y + 120, xx + 24, y + 144), outline=(30, 30, 30), width=2)
        if k == 0:
            d.line((xx + 4, y + 132, xx + 10, y + 140), fill=(20, 40, 120), width=4)
            d.line((xx + 10, y + 140, xx + 22, y + 120), fill=(20, 40, 120), width=4)
        d.text((xx + 34, y + 132), o, font=_pf(FK, 23), fill=(30, 30, 30), anchor="lm")
        xx += 190
    y += 220
    small = ["1. 신청서는 11월 28일(금) 18:00까지 재단 누리집에서 온라인으로 제출합니다.",
             "2. 서류 심사 합격자에 한하여 12월 중 면접을 실시하며, 일정은 개별 통보합니다.",
             "3. 제출된 서류는 반환하지 않습니다."]
    for s in small:
        d.text((x0, y), s, font=_pf(FK, 20), fill=(90, 90, 90))
        y += 30
    y += 40
    d.text((W / 2, y), KO["date"], font=_pf(FK, 28), fill=(20, 20, 20), anchor="mm")
    y += 70
    d.text((x1 - 470, y), KO["sign"][0], font=_pf(FK, 28), fill=(20, 20, 20), anchor="lm")
    d.text((x1, y), KO["sign"][1], font=_pf(FK, 28), fill=(20, 20, 20), anchor="rm")
    d.line((x1 - 360, y + 22, x1 - 180, y + 22), fill=(80, 80, 80), width=1)
    d.rectangle((0, H - 70, W, H), fill=(240, 243, 248))
    d.text((W / 2, H - 35), KO["foot"], font=_pf(FK, 22), fill=(60, 60, 60), anchor="mm")
    im.save(str(path))


def _wrap_px(d, text, font, width):
    """Перенос по пробелам; слово длиннее строки режется по знакам (корейский, японский)."""
    out, cur = [], ""
    for w in text.split(" "):
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


# ─── 54: английское объявление (перевод на хинди) ──────────────────────

EN = {
    "org": "RIVERSIDE MUNICIPAL COUNCIL",
    "title": "Public Notice: Renewal of Street Vendor Licences for 2027",
    "lead": ("All holders of street vendor licences issued by Riverside Municipal Council are reminded that "
             "current licences expire on 31 December 2026. Vendors who wish to continue trading at the "
             "weekly markets, the bus terminal or along Canal Road must renew their licence before that date. "
             "Trading without a valid licence may result in the confiscation of goods and a fine."),
    "steps_h": "How to renew your licence",
    "steps": [
        "Collect the renewal form (Form SV-2) from any ward office or download it from the Council website.",
        "Attach a recent passport-size photograph, a copy of your identity card and your current licence.",
        "Food vendors must also attach a health certificate issued within the last six months.",
        "Submit the completed form at the Licensing Counter, Ground Floor, Town Hall, and pay the fee.",
        "Your new licence card will be ready for collection within ten working days. Bring your receipt.",
    ],
    "fee_h": "Licence fees",
    "fees": [("Licence category", "Annual fee", "Late fee (after 31 Dec)"),
             ("Fixed stall, market area", "₹ 4,800", "₹ 1,200"),
             ("Mobile cart (food)", "₹ 3,600", "₹ 900"),
             ("Mobile cart (non-food)", "₹ 2,400", "₹ 600"),
             ("Seasonal / festival stall", "₹ 1,500", "₹ 400")],
    "note": ("Vendors aged 60 and above, and vendors with a disability certificate, pay 50% of the annual "
             "fee. Senior citizens may ask a family member to submit the form on their behalf."),
    "contact_h": "Need help?",
    "contact": ["Licensing Section, Town Hall, Station Road, Riverside",
                "Open Monday to Saturday, 10:00 a.m. – 4:30 p.m.",
                "Phone: 0471 255 3190   ·   Email: licensing@riverside-council.example",
                "Help desk at Gandhi Market every Wednesday, 9:00 a.m. – 12:00 noon"],
    "sign": ["By order,", "Meera Iyer", "Commissioner, Riverside Municipal Council", "Date: 2 November 2026"],
}


def pdf_en_notice_hi(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    c.setFillColorRGB(0.12, 0.27, 0.45)
    c.rect(0, H - 70, W, 70, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("sansb", 15)
    c.drawCentredString(W / 2, H - 44, EN["org"])
    c.setFillColorRGB(0.1, 0.1, 0.1)
    y = H - 110
    for ln in _wrap(c, EN["title"], "serifb", 17, W - 120):
        c.setFont("serifb", 17)
        c.drawCentredString(W / 2, y, ln)
        y -= 22
    y = _para(c, EN["lead"], 60, y - 10, W - 120, "serif", 10.5, 14.5, align="justify") - 12
    c.setFont("sansb", 12)
    c.setFillColorRGB(0.12, 0.27, 0.45)
    c.drawString(60, y, EN["steps_h"])
    y -= 20
    for k, s in enumerate(EN["steps"], 1):
        c.setFillColorRGB(0.12, 0.27, 0.45)
        c.circle(70, y + 3.5, 8, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("sansb", 9)
        c.drawCentredString(70, y + 0.5, str(k))
        y = _para(c, s, 86, y, W - 146, "serif", 10.5, 14) - 5
    y -= 8
    c.setFont("sansb", 12)
    c.setFillColorRGB(0.12, 0.27, 0.45)
    c.drawString(60, y, EN["fee_h"])
    y -= 26
    cw = [215, 120, 140]
    for r, row in enumerate(EN["fees"]):
        x = 60
        for k, v in enumerate(row):
            if r == 0:
                c.setFillColorRGB(0.86, 0.9, 0.96)
                c.rect(x, y - 7, cw[k], 22, fill=1, stroke=0)
            c.setStrokeColorRGB(0.4, 0.4, 0.4)
            c.setLineWidth(0.6)
            c.rect(x, y - 7, cw[k], 22, fill=0, stroke=1)
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.setFont("sansb" if r == 0 else "sans", 10)
            if k and r:
                c.drawRightString(x + cw[k] - 8, y, v)
            else:
                c.drawString(x + 6, y, v)
            x += cw[k]
        y -= 22
    y = _para(c, EN["note"], 60, y - 14, W - 120, "serif", 9.5, 13, color=(0.25, 0.25, 0.25)) - 12
    # рамка контактов
    bh = 92
    c.setFillColorRGB(0.97, 0.95, 0.88)
    c.setStrokeColorRGB(0.75, 0.55, 0.15)
    c.setLineWidth(1.2)
    c.roundRect(60, y - bh, 300, bh, 6, fill=1, stroke=1)
    c.setFillColorRGB(0.45, 0.3, 0.05)
    c.setFont("sansb", 11)
    c.drawString(72, y - 18, EN["contact_h"])
    yy = y - 34
    for ln in EN["contact"]:
        for l2 in _wrap(c, ln, "sans", 8.3, 276):
            c.setFont("sans", 8.3)
            c.setFillColorRGB(0.15, 0.15, 0.15)
            c.drawString(72, yy, l2)
            yy -= 11.5
    sy = y - bh - 26
    for k, s in enumerate(EN["sign"]):
        c.setFont("serifb" if k == 1 else "serif", 10.5)
        c.drawRightString(W - 60, sy, s)
        sy -= 15
    c.setFont("sans", 7.5)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawCentredString(W / 2, 30, "Notice No. RMC/LIC/2026/114  ·  This notice is also available at all ward offices.")
    c.save()


# ─── 55: испанский буклет в три сложения ───────────────────────────────

ES = {
    "p1_h": "¿Quiénes somos?",
    "p1": ("El Centro Comunitario La Alameda nació en 2009 gracias a un grupo de vecinas que querían un "
           "lugar donde aprender, compartir y cuidarse mutuamente. Hoy recibimos a más de seiscientas "
           "personas cada semana, desde niños pequeños hasta abuelos que vuelven a estudiar."),
    "p1b": ("Todas nuestras actividades son gratuitas o tienen un coste simbólico, y se financian con el "
            "apoyo del Ayuntamiento de Villaseca y de cientos de voluntarios."),
    "p1_call": "¡Únete a nuestra familia!",
    "p2_h": "Talleres de otoño",
    "p2": [("Cerámica para principiantes", "lunes y miércoles, 18:00–20:00"),
           ("Huerto urbano en la azotea", "martes, 10:00–12:00"),
           ("Informática básica para mayores", "jueves, 11:00–12:30"),
           ("Guitarra española", "viernes, 17:30–19:00"),
           ("Cocina saludable con legumbres", "sábados alternos, 10:30–13:00"),
           ("Apoyo escolar (Primaria y ESO)", "de lunes a jueves, 16:00–18:00"),
           ("Yoga suave para todas las edades", "miércoles, 9:30–10:30"),
           ("Club de lectura «Páginas compartidas»", "primer martes de cada mes, 19:00")],
    "p2_fee": "Cuota anual de socio: 15 €. Jubilados, estudiantes y personas desempleadas: ¡gratis!",
    "p2_note": ("Las plazas son limitadas. La inscripción se abre el 1 de septiembre y se realiza por orden "
                "de llegada. ¿Tienes dudas? Pregunta en recepción."),
    "p3_h": "Centro Comunitario",
    "p3_h2": "La Alameda",
    "p3_tag": "Aprender juntos, vivir mejor",
    "p3_contact": ["Calle de los Almendros, 14", "28941 Villaseca (Madrid)", "Teléfono: 918 452 637",
                   "info@laalameda-centro.example", "Horario: lunes a sábado, 9:00–21:00"],
    "p3_foot": "Con la colaboración del Ayuntamiento de Villaseca",
}


def pdf_es_trifold(path):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    _rl_fonts()
    W, H = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=(W, H))
    pw = W / 3
    cols = [(0.96, 0.93, 0.86), (0.88, 0.94, 0.90), (0.16, 0.36, 0.33)]
    for k, col in enumerate(cols):
        c.setFillColorRGB(*col)
        c.rect(k * pw, 0, pw, H, fill=1, stroke=0)
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.setDash(3, 3)
    for k in (1, 2):
        c.line(k * pw, 0, k * pw, H)
    c.setDash()
    m = 26
    # панель 1
    x = m
    c.setFillColorRGB(0.72, 0.33, 0.12)
    c.setFont("serifb", 22)
    c.drawString(x, H - 60, ES["p1_h"])
    y = _para(c, ES["p1"], x, H - 92, pw - 2 * m, "serif", 10.5, 15, align="justify") - 10
    y = _para(c, ES["p1b"], x, y, pw - 2 * m, "serif", 10.5, 15, align="justify") - 22
    # «фото» — плашка с подписью
    c.setFillColorRGB(0.82, 0.74, 0.6)
    c.roundRect(x, y - 150, pw - 2 * m, 150, 8, fill=1, stroke=0)
    c.setFillColorRGB(0.95, 0.9, 0.8)
    c.circle(x + 70, y - 70, 32, fill=1, stroke=0)
    c.circle(x + 150, y - 85, 26, fill=1, stroke=0)
    c.setFillColorRGB(0.35, 0.25, 0.15)
    c.setFont("sans", 8)
    c.drawString(x + 8, y - 142, "Taller de cerámica, primavera de 2026")
    c.setFillColorRGB(0.72, 0.33, 0.12)
    c.setFont("serifb", 17)
    c.drawCentredString(pw / 2, 50, ES["p1_call"])
    # панель 2
    x = pw + m
    c.setFillColorRGB(0.12, 0.42, 0.3)
    c.setFont("serifb", 22)
    c.drawString(x, H - 60, ES["p2_h"])
    y = H - 95
    for name, when in ES["p2"]:
        c.setFillColorRGB(0.12, 0.42, 0.3)
        c.circle(x + 4, y + 3.5, 3.2, fill=1, stroke=0)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        y = _para(c, name, x + 14, y, pw - 2 * m - 14, "sansb", 10.5, 14)
        y = _para(c, when, x + 14, y, pw - 2 * m - 14, "sans", 9.5, 13, color=(0.3, 0.3, 0.3)) - 9
    y = _para(c, ES["p2_fee"], x, y - 4, pw - 2 * m, "sansb", 10, 14, color=(0.72, 0.33, 0.12)) - 10
    nl = len(_wrap(c, ES["p2_note"], "serif", 10, pw - 2 * m - 8))
    c.setFillColorRGB(1, 1, 1)
    c.roundRect(x - 6, y - nl * 14 - 8, pw - 2 * m + 12, nl * 14 + 18, 6, fill=1, stroke=0)
    _para(c, ES["p2_note"], x + 4, y - 4, pw - 2 * m - 8, "serif", 10, 14, color=(0.2, 0.2, 0.2))
    # панель 3 — обложка и контакты
    x = 2 * pw + m
    c.setFillColorRGB(1, 1, 1)
    c.setFont("serifb", 22)
    c.drawCentredString(2 * pw + pw / 2, H - 120, ES["p3_h"])
    c.setFont("serifb", 34)
    c.setFillColorRGB(0.98, 0.82, 0.45)
    c.drawCentredString(2 * pw + pw / 2, H - 162, ES["p3_h2"])
    c.setFillColorRGB(0.9, 0.95, 0.93)
    c.setFont("serif", 13)
    c.drawCentredString(2 * pw + pw / 2, H - 192, ES["p3_tag"])
    # дерево-эмблема
    cx = 2 * pw + pw / 2
    c.setFillColorRGB(0.98, 0.82, 0.45)
    c.circle(cx, H - 275, 48, fill=1, stroke=0)
    c.setFillColorRGB(0.16, 0.36, 0.33)
    c.rect(cx - 5, H - 330, 10, 40, fill=1, stroke=0)
    c.setStrokeColorRGB(0.98, 0.82, 0.45)
    c.setLineWidth(1)
    c.line(x, 210, 3 * pw - m, 210)
    y = 188
    for ln in ES["p3_contact"]:
        c.setFillColorRGB(1, 1, 1)
        c.setFont("sans", 11)
        c.drawString(x, y, ln)
        y -= 18
    c.setFont("sans", 7.5)
    c.setFillColorRGB(0.8, 0.88, 0.85)
    c.drawString(x, 30, ES["p3_foot"])
    c.save()


# ─── 56: португальская презентация ─────────────────────────────────────

PT = {
    "t1": "Cooperativa Agrícola Serra Verde",
    "t1s": "Relatório do terceiro trimestre de 2026 · Assembleia de cooperados, 14 de novembro",
    "t2": "Resultados financeiros do trimestre",
    "table": [("Indicador", "3.º trim. 2025", "3.º trim. 2026", "Variação"),
              ("Receita bruta (R$ mil)", "4.215", "5.038", "+19,5%"),
              ("Custos operacionais (R$ mil)", "3.102", "3.476", "+12,1%"),
              ("Sobras líquidas (R$ mil)", "684", "1.011", "+47,8%"),
              ("Cooperados ativos", "312", "347", "+35"),
              ("Hectares certificados", "1.840", "2.265", "+23,1%")],
    "t3": "Produção por cultura",
    "cats": ["Café arábica", "Feijão", "Milho", "Mandioca", "Laranja"],
    "s25": (820, 410, 1350, 960, 530),
    "s26": (905, 455, 1290, 1120, 610),
    "chart_title": "Produção (toneladas), 3.º trimestre",
    "t4": "Do campo ao armazém: como funciona a recepção",
    "steps": [("Colheita", "Os cooperados entregam o produto nos postos de coleta até as 16h."),
              ("Classificação", "Amostras são pesadas e avaliadas quanto à umidade e às impurezas."),
              ("Armazenamento", "O lote recebe etiqueta própria e segue para o silo correspondente.")],
    "t4note": "Novo: postos de coleta em Pedra Branca e São Joaquim a partir de janeiro.",
    "notes": ("Lembrar que a ampliação dos postos foi aprovada na assembleia de junho. "
              "Mencionar o apoio da prefeitura na pavimentação da estrada vicinal e abrir para perguntas "
              "sobre o calendário de entregas da safra de inverno."),
}


def pptx_pt_slides(path):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt
    pr = Presentation()
    pr.slide_width, pr.slide_height = Inches(13.333), Inches(7.5)
    green = RGBColor(0x2E, 0x6B, 0x3A)
    # 1. титул
    s = pr.slides.add_slide(pr.slide_layouts[0])
    s.shapes.title.text = PT["t1"]
    s.placeholders[1].text = PT["t1s"]
    t, st = s.shapes.title, s.placeholders[1]
    t.left, t.top, t.width, t.height = Inches(0.9), Inches(2.0), Inches(11.5), Inches(1.5)
    st.left, st.top, st.width, st.height = Inches(0.9), Inches(3.7), Inches(11.5), Inches(1.4)
    band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(6.6), pr.slide_width, Inches(0.9))
    band.fill.solid()
    band.fill.fore_color.rgb = green
    band.line.fill.background()
    band.text_frame.text = "Juntos, colhemos mais"
    band.text_frame.paragraphs[0].runs[0].font.size = Pt(20)
    band.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    # 2. таблица
    s = pr.slides.add_slide(pr.slide_layouts[5])
    s.shapes.title.text = PT["t2"]
    rows, cols = len(PT["table"]), 4
    gt = s.shapes.add_table(rows, cols, Inches(0.8), Inches(1.7), Inches(11.7), Inches(4.2)).table
    gt.columns[0].width = Inches(4.5)
    for k in (1, 2, 3):
        gt.columns[k].width = Inches(2.4)
    for r, row in enumerate(PT["table"]):
        for k, v in enumerate(row):
            cell = gt.cell(r, k)
            cell.text = v
            para = cell.text_frame.paragraphs[0]
            para.runs[0].font.size = Pt(18)
            if k:
                from pptx.enum.text import PP_ALIGN
                para.alignment = PP_ALIGN.RIGHT
    tb = s.shapes.add_textbox(Inches(0.8), Inches(6.2), Inches(11), Inches(0.5))
    tb.text_frame.text = "Valores em milhares de reais, sem correção pela inflação."
    tb.text_frame.paragraphs[0].runs[0].font.size = Pt(13)
    tb.text_frame.paragraphs[0].runs[0].font.italic = True
    # 3. диаграмма
    s = pr.slides.add_slide(pr.slide_layouts[5])
    s.shapes.title.text = PT["t3"]
    cd = CategoryChartData()
    cd.categories = PT["cats"]
    cd.add_series("2025", PT["s25"])
    cd.add_series("2026", PT["s26"])
    ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.5),
                            cd).chart
    ch.has_title = True
    ch.chart_title.text_frame.text = PT["chart_title"]
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    ch.plots[0].has_data_labels = True
    ch.plots[0].data_labels.font.size = Pt(11)
    ch.value_axis.has_title = True
    ch.value_axis.axis_title.text_frame.text = "Toneladas"
    # 4. сгруппированные фигуры + заметки
    s = pr.slides.add_slide(pr.slide_layouts[5])
    s.shapes.title.text = PT["t4"]
    grp = s.shapes.add_group_shape()
    for k, (h, t) in enumerate(PT["steps"]):
        left = Inches(0.8 + k * 4.1)
        box = grp.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(2.0), Inches(3.5), Inches(3.0))
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor(0xE6, 0xF2, 0xE4)
        box.line.color.rgb = green
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = h
        tf.paragraphs[0].runs[0].font.size = Pt(24)
        tf.paragraphs[0].runs[0].font.bold = True
        tf.paragraphs[0].runs[0].font.color.rgb = green
        p = tf.add_paragraph()
        p.text = t
        p.runs[0].font.size = Pt(16)
        p.runs[0].font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        if k < 2:
            ar = grp.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, left + Inches(3.55), Inches(3.25), Inches(0.5),
                                      Inches(0.5))
            ar.fill.solid()
            ar.fill.fore_color.rgb = green
    nb = s.shapes.add_textbox(Inches(0.8), Inches(5.6), Inches(11.7), Inches(0.8))
    nb.text_frame.text = PT["t4note"]
    nb.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    nb.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xB0, 0x40, 0x10)
    s.notes_slide.notes_text_frame.text = PT["notes"]
    for sl in list(pr.slides)[1:]:                     # макеты 4:3 — заголовок растянуть на 16:9
        t = sl.shapes.title
        t.left, t.top, t.width, t.height = Inches(0.8), Inches(0.35), Inches(11.7), Inches(1.1)
    pr.save(str(path))


# ─── 57: многолистовой Excel ───────────────────────────────────────────

def xlsx_multi(path):
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    head = PatternFill("solid", fgColor="1F4E78")
    wb = Workbook()
    ws = wb.active
    ws.title = "Сводка"
    ws.merge_cells("A1:E1")
    ws["A1"] = "ООО «Прибрежные технологии» — сводка продаж за III квартал 2026 года"
    ws["A1"].font = Font(bold=True, size=14, color="1F4E78")
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A2:E2")
    ws["A2"] = ("Данные сверены с бухгалтерией 12.10.2026. Суммы в рублях с НДС; доля рассчитана от общей "
                "выручки компании за квартал, а план — по бюджету, утверждённому советом директоров.")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 48
    hdr = ("Направление", "Выручка", "План", "Выполнение плана", "Доля в выручке")
    rows = [("Промышленные датчики", 18450000, 17000000), ("Системы учёта воды", 9730500, 11000000),
            ("Сервисное обслуживание", 6215800, 6000000), ("Обучение персонала", 1184000, 1500000)]
    for k, h in enumerate(hdr, 1):
        cl = ws.cell(4, k, h)
        cl.font = Font(bold=True, color="FFFFFF")
        cl.fill = head
        cl.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        cl.border = box
    ws.row_dimensions[4].height = 32
    for r, (n, rev, plan) in enumerate(rows, 5):
        ws.cell(r, 1, n)
        ws.cell(r, 2, rev).number_format = '#,##0.00 "₽"'
        ws.cell(r, 3, plan).number_format = '#,##0.00 "₽"'
        ws.cell(r, 4, "=B%d/C%d" % (r, r)).number_format = "0.0%"
        ws.cell(r, 5, "=B%d/$B$9" % r).number_format = "0.0%"
        for k in range(1, 6):
            ws.cell(r, k).border = box
    ws["A9"] = "Итого"
    ws["A9"].font = Font(bold=True)
    ws["B9"] = "=SUM(B5:B8)"
    ws["C9"] = "=SUM(C5:C8)"
    ws["D9"] = "=B9/C9"
    for a in ("B9", "C9"):
        ws[a].number_format = '#,##0.00 "₽"'
        ws[a].font = Font(bold=True)
    ws["D9"].number_format = "0.0%"
    ws["B6"].comment = Comment("Недовыполнение связано с переносом двух муниципальных контрактов на IV квартал.",
                               "Карина Мельникова")
    for col, w in zip("ABCDE", (30, 18, 18, 14, 14)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "B5"

    ws2 = wb.create_sheet("Продажи по регионам")
    ws2.merge_cells("A1:F1")
    ws2["A1"] = "Продажи по регионам и месяцам"
    ws2["A1"].font = Font(bold=True, size=13)
    regs = ["Приморский край", "Хабаровский край", "Сахалинская область", "Камчатский край",
            "Магаданская область", "Амурская область"]
    for k, h in enumerate(("Регион", "Июль", "Август", "Сентябрь", "Итого", "Рост к II кв."), 1):
        cl = ws2.cell(2, k, h)
        cl.font = Font(bold=True)
        cl.fill = PatternFill("solid", fgColor="DDEBF7")
        cl.border = box
    rnd = random.Random(57)
    for r, reg in enumerate(regs, 3):
        ws2.cell(r, 1, reg).border = box
        for k in range(2, 5):
            v = ws2.cell(r, k, rnd.randrange(800, 4800) * 1000)
            v.number_format = '#,##0 "₽"'
            v.border = box
        ws2.cell(r, 5, "=SUM(B%d:D%d)" % (r, r)).number_format = '#,##0 "₽"'
        ws2.cell(r, 6, round(rnd.uniform(-0.08, 0.22), 3)).number_format = "+0.0%;-0.0%"
    ws2.column_dimensions["A"].width = 26
    for col in "BCDEF":
        ws2.column_dimensions[col].width = 15
    ws2.freeze_panes = "B3"

    ws3 = wb.create_sheet("Риски и комментарии")
    for k, h in enumerate(("№", "Риск", "Вероятность", "Меры", "Ответственный"), 1):
        cl = ws3.cell(1, k, h)
        cl.font = Font(bold=True, color="FFFFFF")
        cl.fill = head
    risks = [
        ("Задержка поставок микросхем из-за смены логистического оператора во Владивостокском порту",
         0.35, "Заключить резервный договор с поставщиком из Новосибирска, держать запас на шесть недель",
         "Р. Т. Ахмедов"),
        ("Рост курса юаня более чем на 10 % к концу года", 0.2,
         "Перевести часть закупок на долгосрочные контракты с фиксированной ценой", "О. В. Лаптева"),
        ("Отток инженеров сервисной службы в Хабаровске", 0.15,
         "Пересмотреть систему премий и запустить программу наставничества для новых сотрудников",
         "И. Н. Сорокин"),
    ]
    for r, (risk, p, act, who) in enumerate(risks, 2):
        ws3.cell(r, 1, r - 1)
        ws3.cell(r, 2, risk)
        ws3.cell(r, 3, p).number_format = "0%"
        ws3.cell(r, 4, act)
        ws3.cell(r, 5, who)
        for k in range(1, 6):
            ws3.cell(r, k).alignment = Alignment(wrap_text=True, vertical="top")
        ws3.row_dimensions[r].height = 62
    for col, w in zip("ABCDE", (5, 42, 13, 44, 18)):
        ws3.column_dimensions[col].width = w
    ws3.freeze_panes = "A2"
    for sh in wb.worksheets:                           # печать: альбом, по ширине страницы
        sh.page_setup.orientation = "landscape"
        sh.sheet_properties.pageSetUpPr.fitToPage = True
        sh.page_setup.fitToWidth = 1
        sh.page_setup.fitToHeight = 0
    wb.save(str(path))


# ─── 58: сложный Word ──────────────────────────────────────────────────

RUX = {
    "hdr_first": "Фонд поддержки сельских библиотек «Северное сияние»",
    "hdr": "Годовой отчёт за 2026 год",
    "ftr_first": "г. Петрозаводск, ул. Онежская, д. 27 · тел. +7 (8142) 55-31-08",
    "ftr": "Отчёт подготовлен отделом программ фонда",
    "title": "Годовой отчёт фонда за 2026 год",
    "intro": ("В 2026 году фонд продолжил работу в трёх направлениях: обновление книжных фондов, "
              "подключение библиотек к интернету и обучение библиотекарей. Отчёт описывает результаты "
              "каждой программы и расходы, утверждённые попечительским советом."),
    "h_prog": "Программы фонда",
    "cols": [
        ("Обновление книжных фондов. За год сорок две сельские библиотеки Карелии и Мурманской области "
         "получили 18 600 новых книг. Больше всего запросов пришло на детскую литературу и справочники "
         "по садоводству."),
        ("Цифровая библиотека. В двадцати пяти посёлках установлены компьютеры и спутниковые терминалы. "
         "Читатели теперь могут заказывать электронные книги из областной библиотеки, не выезжая в город."),
        ("Школа библиотекаря. Курс повышения квалификации прошли 63 сотрудника. Занятия велись очно "
         "в Петрозаводске и дистанционно, а лучшие выпускники получили гранты на собственные проекты."),
        ("Волонтёры. В работе фонда участвовали 214 добровольцев: они разбирали фонды, проводили "
         "громкие чтения и помогали пожилым читателям освоить электронные каталоги."),
    ],
    "box": "Главное за год: 42 библиотеки, 18 600 книг, 63 выпускника «Школы библиотекаря».",
    "h_fin": "Финансовые результаты",
    "fin": ("Общий бюджет фонда составил 31,4 млн рублей. Основную часть средств предоставили "
            "частные жертвователи, остальное — гранты и средства региональных программ."),
    "fn1": "Без учёта книг, переданных издательствами безвозмездно.",
    "fn2": "Данные аудиторского заключения ООО «Аудит-Онега» от 20 января 2027 года.",
    "table": [("Статья", "План, тыс. руб.", "Факт, тыс. руб.", ""),
              ("Закупка книг", "9 800", "10 240", ""),
              ("Оборудование и связь", "12 500", "11 870", ""),
              ("Обучение", "4 200", "4 615", ""),
              ("Административные расходы", "3 100", "2 980", ""),
              ("Итого", "29 600", "29 705", "")],
    "h_plan": "Планы на 2027 год",
    "plan": ("В 2027 году фонд намерен подключить к интернету ещё тридцать библиотек и открыть "
             "передвижную библиотеку для отдалённых посёлков Беломорского района."),
}


def _fld_toc():
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    return parse_xml(
        '<w:p %s><w:fldSimple w:instr=\' TOC \\o "1-3" \\h \\z \\u \'>'
        '<w:r><w:t xml:space="preserve">Программы фонда\t1</w:t></w:r>'
        '<w:r><w:br/><w:t xml:space="preserve">Финансовые результаты\t2</w:t></w:r>'
        '<w:r><w:br/><w:t xml:space="preserve">Планы на 2027 год\t2</w:t></w:r>'
        '</w:fldSimple></w:p>' % nsdecls("w"))


def _textbox_run(text):
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    return parse_xml(
        '<w:r %s xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
        '<w:pict><v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe">'
        '<v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>'
        '<v:shape id="tbox1" type="#_x0000_t202" style="width:420pt;height:46pt" fillcolor="#EAF1FB" '
        'strokecolor="#2F5597" strokeweight="1pt"><v:textbox>'
        '<w:txbxContent><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:color w:val="1F3864"/>'
        '<w:sz w:val="24"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r></w:p></w:txbxContent>'
        '</v:textbox></v:shape></w:pict></w:r>' % (nsdecls("w"), text))


def _fn_ref(nid):
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    return parse_xml('<w:r %s><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
                     '<w:footnoteReference w:id="%d"/></w:r>' % (nsdecls("w"), nid))


def _add_footnotes(d, notes):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = ['<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>',
            '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r>'
            '</w:p></w:footnote>']
    for nid, t in notes:
        body.append('<w:footnote w:id="%d"><w:p><w:pPr><w:spacing w:after="0"/></w:pPr>'
                    '<w:r><w:rPr><w:vertAlign w:val="superscript"/><w:sz w:val="18"/></w:rPr><w:footnoteRef/></w:r>'
                    '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve"> %s</w:t></w:r></w:p>'
                    '</w:footnote>' % (nid, t))
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:footnotes xmlns:w="%s">%s</w:footnotes>' % (W, "".join(body))).encode("utf-8")
    part = Part(PackURI("/word/footnotes.xml"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml", xml, d.part.package)
    d.part.relate_to(part, RT.FOOTNOTES)


def docx_complex(path):
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls, qn
    from docx.shared import Pt
    d = Document()
    s1 = d.sections[0]
    s1.different_first_page_header_footer = True
    s1.first_page_header.paragraphs[0].text = RUX["hdr_first"]
    s1.first_page_footer.paragraphs[0].text = RUX["ftr_first"]
    s1.header.paragraphs[0].text = RUX["hdr"]
    s1.header.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    s1.footer.paragraphs[0].text = RUX["ftr"]
    d.add_heading(RUX["title"], 0)
    p = d.add_paragraph()
    p.add_run("Содержание").bold = True
    tp = d.add_paragraph()
    tp._p.addnext(_fld_toc())                    # абзац с полем — до sectPr тела
    tp._p.getparent().remove(tp._p)
    d.add_paragraph(RUX["intro"]).alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    d.add_heading(RUX["h_prog"], 1)
    # двухколоночный раздел
    s2 = d.add_section(WD_SECTION.CONTINUOUS)
    for c in s2._sectPr.findall(qn("w:cols")):
        s2._sectPr.remove(c)
    _put(s2._sectPr, parse_xml('<w:cols %s w:num="2" w:space="567"/>' % nsdecls("w")), _SECT_AFTER_COLS)
    for k, t in enumerate(RUX["cols"]):
        head, rest = t.split(". ", 1)
        p = d.add_paragraph()
        p.add_run(head + ". ").bold = True
        p.add_run(rest)
        if k == 0:
            p._p.append(_fn_ref(1))
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    s3 = d.add_section(WD_SECTION.CONTINUOUS)
    s2.different_first_page_header_footer = False     # «особый первый» — только у первой страницы документа
    s3.different_first_page_header_footer = False
    for c in s3._sectPr.findall(qn("w:cols")):
        s3._sectPr.remove(c)
    p = d.add_paragraph()
    p._p.append(_textbox_run(RUX["box"]))
    d.add_heading(RUX["h_fin"], 1)
    p = d.add_paragraph(RUX["fin"])
    p._p.append(_fn_ref(2))
    t = d.add_table(rows=len(RUX["table"]), cols=4)
    t.style = "Table Grid"
    for r, row in enumerate(RUX["table"]):
        for k, v in enumerate(row):
            if v:
                t.cell(r, k).text = v
    # объединения: «Отклонение» над двумя строками справа, итог на две колонки слева
    a = t.cell(0, 3).merge(t.cell(1, 3))
    a.text = "Комментарий"
    b = t.cell(2, 3).merge(t.cell(4, 3))
    b.text = "Экономия на связи позволила расширить программу обучения."
    t.cell(5, 3).text = "+0,3 %"
    for k in range(4):
        for para in t.cell(0, k).paragraphs:
            for run in para.runs:
                run.bold = True
    d.add_heading(RUX["h_plan"], 1)
    d.add_paragraph(RUX["plan"]).alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p = d.add_paragraph("Председатель попечительского совета ______________ А. В. Хейккинен")
    p.paragraph_format.space_before = Pt(18)
    _add_footnotes(d, [(1, RUX["fn1"]), (2, RUX["fn2"])])
    d.save(str(path))


# ─── 59: немецкая веб-страница ─────────────────────────────────────────

HTML_DE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Stadtbibliothek Lindenau &ndash; &Ouml;ffnungszeiten und Veranstaltungen</title>
<style>
body{font-family:Arial,sans-serif;max-width:960px;margin:0 auto;color:#222}
nav ul{list-style:none;display:flex;gap:18px;padding:10px;background:#234;margin:0}
nav a{color:#fff;text-decoration:none}
table{border-collapse:collapse;margin:12px 0}
td,th{border:1px solid #888;padding:6px 10px;vertical-align:top}
th{background:#e4ecf4}
.hinweis{background:#fff6d8;border-left:4px solid #e0a800;padding:8px 12px}
footer{font-size:12px;color:#555;border-top:1px solid #ccc;margin-top:24px;padding-top:8px}
</style>
</head>
<body>
<header>
<h1>Stadtbibliothek Lindenau</h1>
<p>Ihre Bibliothek im Herzen der Altstadt &ndash; seit 1898</p>
</header>
<nav>
<ul>
<li><a href="/">Startseite</a></li>
<li><a href="/katalog">Online-Katalog</a></li>
<li><a href="/veranstaltungen">Veranstaltungen</a>
  <ul>
  <li><a href="/veranstaltungen/kinder">F&uuml;r Kinder und Jugendliche</a></li>
  <li><a href="/veranstaltungen/erwachsene">F&uuml;r Erwachsene</a></li>
  </ul>
</li>
<li><a href="/service">Service &amp; Ausleihe</a></li>
<li><a href="/kontakt">Kontakt</a></li>
</ul>
</nav>
<main>
<h2>&Ouml;ffnungszeiten ab 1.&nbsp;November&nbsp;2026</h2>
<p>Wegen der <b>Sanierung des Lesesaals</b> gelten im Winterhalbjahr ge&auml;nderte &Ouml;ffnungszeiten.
Die <i>Kinder- und Jugendbibliothek</i> im Erdgeschoss bleibt w&auml;hrend der Bauarbeiten
uneingeschr&auml;nkt ge&ouml;ffnet.<sup>1</sup></p>
<table>
<thead>
<tr><th rowspan="2">Bereich</th><th colspan="2">Montag&ndash;Freitag</th><th rowspan="2">Samstag</th></tr>
<tr><th>vormittags</th><th>nachmittags</th></tr>
</thead>
<tbody>
<tr><td>Hauptbibliothek</td><td>10:00&ndash;13:00</td><td>14:00&ndash;19:00</td><td>10:00&ndash;14:00</td></tr>
<tr><td>Kinder- und Jugendbibliothek</td><td colspan="2">durchgehend 9:30&ndash;18:00</td><td>10:00&ndash;13:00</td></tr>
<tr><td>Lesesaal und Zeitschriftenarchiv</td><td colspan="3"><b>geschlossen</b> bis voraussichtlich M&auml;rz&nbsp;2027</td></tr>
<tr><td>Medienr&uuml;ckgabe&shy;automat</td>
<td colspan="3">
  <table>
  <tr><th>Standort</th><th>Zug&auml;nglichkeit</th></tr>
  <tr><td>Haupteingang Marktstra&szlig;e</td><td>rund um die Uhr</td></tr>
  <tr><td>Nebeneingang Gerbergasse</td><td>nur zu den &Ouml;ffnungszeiten</td></tr>
  </table>
</td></tr>
</tbody>
</table>
<p class="hinweis"><b>Hinweis:</b> Die Ausleihfrist f&uuml;r B&uuml;cher betr&auml;gt vier Wochen und kann
zweimal online verl&auml;ngert werden. Vorbestellte Medien liegen sieben Tage zur Abholung bereit.</p>
<h2>Veranstaltungen im November</h2>
<ul>
<li><b>Mi, 4.&nbsp;11., 16:00&nbsp;Uhr</b> &ndash; Bilderbuchkino &bdquo;Der kleine Fuchs und der Wintermond&ldquo; (ab 4&nbsp;Jahren)</li>
<li><b>Do, 12.&nbsp;11., 19:30&nbsp;Uhr</b> &ndash; Lesung mit der Krimiautorin <i>Henrike Altmann</i> aus ihrem Roman &bdquo;Nebel &uuml;ber der Saale&ldquo;; Eintritt 6&nbsp;&euro;, erm&auml;&szlig;igt 4&nbsp;&euro;</li>
<li><b>Sa, 21.&nbsp;11., 10:00&ndash;13:00&nbsp;Uhr</b> &ndash; Digitalsprechstunde: Hilfe bei E-Book-Readern, Tablets und der <a href="/onleihe">Onleihe</a></li>
<li><b>Di, 24.&nbsp;11., 18:00&nbsp;Uhr</b> &ndash; Vortrag &bdquo;Hochwasserschutzma&szlig;nahmen in der Lindenauer Auenlandschaft&ldquo;</li>
</ul>
<p>F&uuml;r alle Veranstaltungen ist eine Anmeldung &uuml;ber das <a href="/anmeldung">Veranstaltungsanmeldeformular</a>
oder telefonisch unter 0341&nbsp;48&nbsp;29&nbsp;117 erforderlich.</p>
</main>
<footer>
<p><sup>1</sup> Der Zugang erfolgt w&auml;hrend der Bauphase ausschlie&szlig;lich &uuml;ber den Nebeneingang Gerbergasse.</p>
<p>&copy; 2026 Stadtbibliothek Lindenau &middot; <a href="/impressum">Impressum</a> &middot; <a href="/datenschutz">Datenschutzerkl&auml;rung</a></p>
</footer>
</body>
</html>
"""


def html_de_nested(path):
    Path(path).write_text(HTML_DE, encoding="utf-8")


# ─── 60: турецкое официальное уведомление ──────────────────────────────

TR = {
    "org": ["T.C.", "YEŞİLOVA BELEDİYESİ", "Fen İşleri Müdürlüğü"],
    "num": "Sayı: E-48217630-754-2026/1182",
    "date": "Tarih: 21.10.2026",
    "subj": "Konu: Kış dönemi kar küreme çalışmaları ve araç park düzenlemesi",
    "lead": ("Belediyemiz sınırları içinde 1 Aralık 2026 – 15 Mart 2027 tarihleri arasında uygulanacak kış "
             "dönemi tedbirleri aşağıda belirtilmiştir. Sayın vatandaşlarımızın bu düzenlemelere uyması, "
             "karla mücadele ekiplerinin yollara zamanında ulaşabilmesi için büyük önem taşımaktadır."),
    "list": [
        ("1.", "Araç park düzenlemesi", 0),
        ("1.1.", "Kar yağışı sırasında ana caddelerde yolun her iki tarafına araç park edilmesi yasaktır.", 1),
        ("1.2.", "Yasağa uymayan araçlar, ekiplerin çalışmasını engellediği takdirde çekici ile otoparka taşınacaktır.", 1),
        ("a)", "Çekme ücreti ve otopark bedeli araç sahibinden tahsil edilir.", 2),
        ("b)", "İtirazlar, tutanak tarihinden itibaren on beş gün içinde yazılı olarak yapılabilir.", 2),
        ("2.", "Kaldırımların temizlenmesi", 0),
        ("2.1.", "İşyeri ve bina sahipleri, önlerindeki kaldırımı sabah saat 08.00’e kadar kardan ve buzdan "
                 "temizlemekle yükümlüdür.", 1),
        ("2.2.", "Tuz ve kum, mahalle muhtarlıklarından ücretsiz olarak temin edilebilir.", 1),
        ("3.", "İhbar ve iletişim", 0),
        ("3.1.", "Kapanan yollar, devrilen ağaçlar ve buzlanma tehlikesi 7/24 hizmet veren Çözüm Merkezi’ne "
                 "bildirilmelidir.", 1),
    ],
    "table": [("Bölge", "Öncelik", "Sorumlu ekip", "İrtibat"),
              ("İstiklal ve Gazi caddeleri", "1. derece", "Merkez Ekibi", "0 (352) 418 22 10"),
              ("Çamlıca ve Ilıca mahalleleri", "2. derece", "Kuzey Ekibi", "0 (352) 418 22 11"),
              ("Organize Sanayi Bölgesi", "1. derece", "Sanayi Ekibi", "0 (352) 418 22 12"),
              ("Köy ve yayla yolları", "3. derece", "Kırsal Ekip", "0 (352) 418 22 13")],
    "end": "Kamuoyuna saygıyla duyurulur.",
    "sign": ["Müh. İsmail Öztürk", "Fen İşleri Müdürü", "(e-imzalıdır)"],
    "foot": "Cumhuriyet Mah. Atatürk Bulvarı No: 41, 38700 Yeşilova · Çözüm Merkezi: 444 0 938 · www.yesilova-bel.example",
}


def pdf_tr_notice(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    _rl_fonts()
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    # эмблема
    c.setStrokeColorRGB(0.7, 0.1, 0.1)
    c.setLineWidth(2)
    c.circle(85, H - 75, 26, fill=0, stroke=1)
    c.setFillColorRGB(0.7, 0.1, 0.1)
    c.setFont("sansb", 8)
    c.drawCentredString(85, H - 78, "YEŞİLOVA")
    c.setFillColorRGB(0.1, 0.1, 0.1)
    y = H - 55
    for k, t in enumerate(TR["org"]):
        c.setFont("serifb" if k < 2 else "serif", 13 if k == 1 else 11.5)
        c.drawCentredString(W / 2, y, t)
        y -= 17
    y -= 12
    c.setFont("serif", 10.5)
    c.drawString(60, y, TR["num"])
    c.drawRightString(W - 60, y, TR["date"])
    y -= 22
    y = _para(c, TR["subj"], 60, y, W - 120, "serifb", 11, 15) - 8
    y = _para(c, TR["lead"], 60, y, W - 120, "serif", 10.5, 14.5, align="justify", indent=22) - 10
    for mark, text, lvl in TR["list"]:
        x = 60 + lvl * 24
        font = "serifb" if lvl == 0 else "serif"
        c.setFont(font, 10.5)
        c.drawString(x, y, mark)
        y = _para(c, text, x + (22 if lvl < 2 else 18), y, W - 60 - x - 22, font, 10.5, 14,
                  align="justify" if lvl else "left") - 3
    y -= 10
    cw = [165, 70, 110, 130]
    for r, row in enumerate(TR["table"]):
        x = 60
        for k, v in enumerate(row):
            if r == 0:
                c.setFillColorRGB(0.9, 0.9, 0.9)
                c.rect(x, y - 7, cw[k], 21, fill=1, stroke=0)
            c.setLineWidth(0.6)
            c.setStrokeColorRGB(0.3, 0.3, 0.3)
            c.rect(x, y - 7, cw[k], 21, fill=0, stroke=1)
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.setFont("sansb" if r == 0 else "sans", 9.3)
            c.drawString(x + 5, y, v)
            x += cw[k]
        y -= 21
    y -= 20
    c.setFont("serif", 10.5)
    c.drawString(82, y, TR["end"])
    y -= 34
    for k, t in enumerate(TR["sign"]):
        c.setFont("serifb" if k == 0 else "serif", 10.5)
        c.drawCentredString(W - 140, y, t)
        y -= 14
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.line(60, 48, W - 60, 48)
    c.setFont("sans", 7.5)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.drawCentredString(W / 2, 36, TR["foot"])
    c.save()


RECIPES = [
    ("51_ja_vertical", "png", png_ja_vertical, "JA", "RU", "original",
     "JA→: объявление татэгаки — колонки сверху вниз справа налево, вертикальные знаки, таблица, ханко"),
    ("52_ar_letter", "docx", docx_ar_letter, "AR", "RU", "docx_layout",
     "AR→: официальное письмо справа налево (w:bidi, w:rtl), таблица bidiVisual, восточные цифры"),
    ("53_ko_form", "png", png_ko_form, "KO", "RU", "original",
     "KO→: анкета-картинка: поля в рамках, флажки, мелкие указания, полоса с логотипом"),
    ("54_en_notice_hi", "pdf", pdf_en_notice_hi, "EN", "HI", "pdf",
     "EN→HI: объявление, шаги в кружках, таблица сборов, рамка контактов (деванагари в выгрузке)"),
    ("55_es_trifold", "pdf", pdf_es_trifold, "ES", "RU", "pdf",
     "ES→: буклет в три сложения, цветные панели, списки, ñ á ¿ ¡, белый текст на тёмном"),
    ("56_pt_slides", "pptx", pptx_pt_slides, "PT", "RU", "original",
     "PT→: PowerPoint: титул, таблица, родная диаграмма с подписями, группа фигур, заметки"),
    ("57_xlsx_multi", "xlsx", xlsx_multi, "RU", "ZH", "original",
     "RU→ZH: Excel 3 листа, объединения, перенос в ячейках, валюта и %, примечание, закрепление, формулы"),
    ("58_docx_complex", "docx", docx_complex, "RU", "EN", "docx_layout",
     "Word: поле TOC, раздел в 2 колонки, надпись (txbxContent), сноски, особый первый колонтитул, объединённые ячейки"),
    ("59_html_nested", "html", html_de_nested, "DE", "EN", "original",
     "DE→: веб-страница: меню, вложенная таблица colspan/rowspan, инлайн-теги, сущности, составные слова"),
    ("60_tr_notice", "pdf", pdf_tr_notice, "TR", "RU", "pdf",
     "TR→: официальное уведомление, ğ ş ı İ, многоуровневый список 1./1.1./a), таблица, подпись"),
]

