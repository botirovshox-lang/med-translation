"""Сверка первой выгрузки нового файла — инструмент агента-разработчика.

Порядок работы — docs/rules/export-review.md. Сервер ставит каждую первую
выгрузку нового файла в очередь (`STATE["exportReviews"]`, тест
tests/test_export_review.py); этот инструмент её читает, скачивает оригинал
и выгрузку и рисует пары страниц «оригинал | выгрузка» для разбора.

    python tools/export_review.py list [--all]
    python tools/export_review.py fetch PID DIR        # оригинал, выгрузка, карта, проект
    python tools/export_review.py pages DIR [--pages 1,4,6] [--scale 2]
    python tools/export_review.py done RID --report URL [--note ТЕКСТ]
    python tools/export_review.py skip RID [--note ТЕКСТ]

Сервер — ssh-алиас `beget` (переменная MEDCAT_SSH). Чтение базы и файлов
идёт по ssh напрямую; отметка (done/skip) — запись, она идёт через
tools/prod_run.sh (копия базы до запуска). Данные клиента остаются
в DIR на этой машине — в репозиторий их не класть.
"""
import argparse
import json
import re
import shlex
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOST = os.environ.get("MEDCAT_SSH", "beget")
# Имя файла выгрузки задаёт клиент (название проекта): в команду сервера оно
# идёт только через этот фильтр и `shlex.quote`, иначе название вида
# «x'; команда; '» выполнилось бы на сервере от root.
SAFE_NAME = re.compile(r"^[^/\\'\"`$;&|<>\x00-\x1f]+\.(pdf|docx)$")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _plain(t) -> str:
    """Текст клиента для терминала — без управляющих знаков."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(t or ""))
APP = "/opt/med-translation"
PSQL = "sudo -u postgres psql -p 5433 medcat -At -c"
ROOT = Path(__file__).resolve().parent.parent


def ssh(cmd: str, binary: bool = False):
    r = subprocess.run(["ssh", HOST, cmd], capture_output=True)
    if r.returncode != 0:
        sys.exit("ssh: %s" % r.stderr.decode("utf-8", "replace")[:400])
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def doc(key: str):
    out = ssh("%s \"select doc from state_docs where key='%s'\"" % (PSQL, key)).strip()
    return json.loads(out) if out else None


def cmd_list(a):
    q = doc("exportReviews") or []
    rows = [r for r in q if a.all or r.get("status") == "pending"]
    if not rows:
        print("очередь пуста" if not a.all else "строк нет")
        return
    for r in rows:
        print("#%-4s %-8s проект %-5s %-6s %s→%s  %s  «%s»  %s" % (
            r.get("id"), r.get("status"), r.get("project"), r.get("format"),
            r.get("src"), r.get("tgt"), r.get("at"), _plain(r.get("title"))[:60],
            _plain(r.get("report"))))


def cmd_fetch(a):
    out = Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)
    p = doc("projects:%d" % a.pid)
    if not p:
        sys.exit("проекта %d нет" % a.pid)
    (out / "project.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    src = "%s/backend/data/sources" % APP
    names = ssh("ls %s | grep -E '^%d\\.(json|docx|orig\\..*)$' || true" % (src, a.pid)).split()
    for n in names:
        (out / n).write_bytes(ssh("cat %s/%s" % (src, n), binary=True))
    tenant = re.sub(r"[^A-Za-z0-9_-]+", "_", p.get("tenant") or "default")
    exp = "%s/backend/data/exports/%s/%d" % (APP, tenant, a.pid)
    newest = [n.strip() for n in ssh("ls -t %s 2>/dev/null | head -20 || true" % shlex.quote(exp)).split("\n")]
    newest = [n for n in newest if SAFE_NAME.match(n)]
    # В каталоге выгрузок лежит и копия оригинала под его именем — её
    # не берём; из выгрузок — самая свежая, PDF первым.
    cand = [n for n in newest if n and n != (p.get("fileName") or "") and n.endswith((".pdf", ".docx"))]
    got = next((n for n in cand if n.endswith(".pdf")), None) or (cand[0] if cand else None)
    if got:
        (out / ("export" + Path(got).suffix)).write_bytes(ssh("cat %s" % shlex.quote(exp + "/" + got), binary=True))
    print("скачано в %s: %s; выгрузка: %s" % (out, ", ".join(names + ["project.json"]), got or "нет"))


def _render(pdf: Path, outdir: Path, scale: float, pages=None) -> int:
    import pypdfium2 as pdfium
    outdir.mkdir(parents=True, exist_ok=True)
    d = pdfium.PdfDocument(str(pdf))
    for i in range(len(d)):
        if pages and (i + 1) not in pages:
            continue
        d[i].render(scale=scale).to_pil().save(outdir / ("%02d.png" % (i + 1)))
    return len(d)


def _original_pdf(dirp: Path) -> "Path | None":
    """Оригинал страницами выгрузки: у PDF-«ленты» — виртуальными страницами
    (`pdf_panels`), иначе сам файл; .docx — через LibreOffice, если он есть."""
    orig = next(iter(sorted(dirp.glob("*.orig.pdf"))), None)
    sidecar = next(iter(sorted(p for p in dirp.glob("*.json") if p.stem.isdigit())), None)
    if orig is not None:
        virt = None
        if sidecar is not None:
            virt = ((json.loads(sidecar.read_text(encoding="utf-8")).get("layout") or {}).get("virt"))
        if virt:
            sys.path.insert(0, str(ROOT / "backend"))
            import pdf_panels
            v = pdf_panels._compose(orig.read_bytes(), virt,
                                    frozenset(int(k) for k in (virt.get("whole") or [])))
            outp = dirp / "orig_pages.pdf"
            outp.write_bytes(v)
            return outp
        return orig
    for docx in sorted(dirp.glob("*.docx")):
        if docx.name.startswith("export"):
            continue
        r = subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(dirp), str(docx)],
                           capture_output=True)
        pdf = dirp / (docx.stem + ".pdf")
        if r.returncode == 0 and pdf.exists():
            return pdf
        print("нет LibreOffice (soffice) — оригинал .docx не нарисован")
    return None


def cmd_pages(a):
    dirp = Path(a.dir)
    pages = {int(x) for x in a.pages.split(",")} if a.pages else None
    orig = _original_pdf(dirp)
    exp = dirp / "export.pdf"
    if not exp.exists() and (dirp / "export.docx").exists():
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(dirp),
                        str(dirp / "export.docx")], capture_output=True)
    if orig is None or not exp.exists():
        sys.exit("нет оригинала или выгрузки PDF в %s" % dirp)
    n1 = _render(orig, dirp / "o", a.scale, pages)
    n2 = _render(exp, dirp / "r", a.scale, pages)
    if n1 != n2:
        print("страниц: оригинал %d, выгрузка %d — сверять по содержанию" % (n1, n2))
    from PIL import Image
    pairs = dirp / "pairs"
    pairs.mkdir(exist_ok=True)
    for f in sorted((dirp / "r").glob("*.png")):
        o = dirp / "o" / f.name
        if not o.exists():
            continue
        A, B = Image.open(o).convert("RGB"), Image.open(f).convert("RGB")
        if A.size != B.size:
            B = B.resize(A.size)
        s = Image.new("RGB", (A.width * 2 + 12, A.height), (220, 30, 80))
        s.paste(A, (0, 0))
        s.paste(B, (A.width + 12, 0))
        s.save(pairs / f.name)
    print("пары страниц: %s (слева оригинал, справа выгрузка)" % pairs)


def _mark(a, status):
    script = """import json, urllib.request
env = dict(l.strip().split("=", 1) for l in open("/etc/medcat/env", encoding="utf-8")
           if "=" in l and not l.lstrip().startswith("#"))
def call(m, path, body=None, tok=None):
    rq = urllib.request.Request("http://127.0.0.1:8000" + path, method=m,
                                data=json.dumps(body).encode() if body is not None else None,
                                headers={"Content-Type": "application/json",
                                         **({"Authorization": "Bearer " + tok} if tok else {})})
    return json.loads(urllib.request.urlopen(rq, timeout=60).read())
tok = call("POST", "/api/auth/login", {"login": "admin",
                                        "password": env["APP_PASSWORD"].strip().strip('"').strip("'")})["token"]
print(call("POST", "/api/admin/export-reviews/%d", %s, tok))
""" % (a.rid, json.dumps({"status": status, "note": a.note or "", "report": getattr(a, "report", "") or ""},
                          ensure_ascii=False))
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
    try:
        subprocess.run(["bash", str(ROOT / "tools" / "prod_run.sh"), f.name], check=True)
    finally:
        os.unlink(f.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list"); s.add_argument("--all", action="store_true")
    s = sub.add_parser("fetch"); s.add_argument("pid", type=int); s.add_argument("dir")
    s = sub.add_parser("pages"); s.add_argument("dir"); s.add_argument("--pages", default="")
    s.add_argument("--scale", type=float, default=2.0)
    s = sub.add_parser("done"); s.add_argument("rid", type=int); s.add_argument("--report", required=True)
    s.add_argument("--note", default="")
    s = sub.add_parser("skip"); s.add_argument("rid", type=int); s.add_argument("--note", default="")
    a = ap.parse_args()
    if a.cmd == "list":
        cmd_list(a)
    elif a.cmd == "fetch":
        cmd_fetch(a)
    elif a.cmd == "pages":
        cmd_pages(a)
    elif a.cmd == "done":
        _mark(a, "done")
    elif a.cmd == "skip":
        _mark(a, "skipped")


if __name__ == "__main__":
    main()
