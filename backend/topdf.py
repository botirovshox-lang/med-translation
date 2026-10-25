# -*- coding: utf-8 -*-
"""PDF из готового .docx — сторонним конвертером (LibreOffice).

ПОЧЕМУ НЕ СОБИРАЕМ PDF САМИ. Оформление у нас уже есть — и ровно там, где
ему место: экспорт «как в оригинале» (`docx_layout`) не собирает документ,
а подменяет текст в ИСХОДНОМ файле, поэтому шрифты, таблицы, картинки и
колонтитулы остаются байт в байт. Собери мы PDF с нуля — потеряли бы всё это
разом, то есть заменили бы точную выгрузку на приблизительную. Значит задача
не «сделать PDF», а «показать УЖЕ ГОТОВЫЙ документ в другом формате», и это
работа вёрстки, которой у нас нет и писать которую незачем.

ПОЧЕМУ ЧЕСТНЫЙ ОТКАЗ, А НЕ ЗАГЛУШКА. Нет конвертера на сервере — отвечаем
«нет конвертера» (инвариант 4). Собранный на скорую руку PDF из голого текста
выглядел бы как выгрузка и не был бы ею: человек отправил бы заказчику
документ без вёрстки, не зная об этом.

ЧТО ЗНАТЬ ПРО СЕРВЕР. Юнит `medcat.service` идёт с `ProtectSystem=full`,
`ProtectHome=read-only` и `PrivateTmp=true`, а писать разрешено только
в `backend/data/`. LibreOffice при первом запуске заводит себе профиль
в домашнем каталоге — и молча ВИСНЕТ, если туда нельзя. Поэтому профиль
и HOME указываются явно, внутрь `data/`.

Один воркер — одна оговорка: конвертация книги занимает десятки секунд.
Обработчик экспорта синхронный, FastAPI выполняет такой в пуле потоков,
поэтому цикл событий не встаёт; но потолок по времени всё равно обязателен,
иначе зависший процесс держит поток до конца жизни сервиса.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

# Имя конвертера можно назвать явно: на разных системах он то `soffice`,
# то `libreoffice`, а в контейнере может лежать вообще не в PATH.
SOFFICE = os.environ.get("SOFFICE_BIN", "").strip()
TIMEOUT = int(os.environ.get("PDF_TIMEOUT", "180"))


class NotAvailable(Exception):
    """Конвертера нет. Не ошибка данных — отсутствие возможности."""


class Failed(Exception):
    """Конвертер есть, но не справился."""


def binary() -> str:
    """Путь к конвертеру или пустая строка. Отдельной функцией, чтобы
    экран экспорта мог спросить ДО нажатия и не предлагать формат,
    которого на этом сервере нет."""
    if SOFFICE:
        return SOFFICE if Path(SOFFICE).exists() else ""
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def available() -> bool:
    return bool(binary())


LOCK_WAIT = int(os.environ.get("PDF_LOCK_WAIT", "600"))
_TLOCK = threading.Lock()
# Фильтр печати по расширению: у Writer, Calc и Impress свои. Нет в списке —
# LibreOffice выбирает сам (`--convert-to pdf`).
FILTERS = {".docx": "pdf:writer_pdf_Export", ".doc": "pdf:writer_pdf_Export",
           ".odt": "pdf:writer_pdf_Export", ".rtf": "pdf:writer_pdf_Export",
           ".xlsx": "pdf:calc_pdf_Export", ".xls": "pdf:calc_pdf_Export",
           ".ods": "pdf:calc_pdf_Export", ".csv": "pdf:calc_pdf_Export",
           ".pptx": "pdf:impress_pdf_Export", ".ppt": "pdf:impress_pdf_Export",
           ".odp": "pdf:impress_pdf_Export",
           ".html": "pdf:writer_web_pdf_Export", ".htm": "pdf:writer_web_pdf_Export"}


@contextmanager
def _soffice_lock(profile_dir: Path):
    """ОДИН LibreOffice на профиль за раз — между ПОТОКАМИ и между ПРОЦЕССАМИ.
    Два soffice с общим профилем не работают параллельно: второй молча
    передаёт файл первому и выходит, не собрав ничего (или собирает чужое).
    Конвертируют и API (скачивание PDF), и воркер (проверка выгрузки перед
    выдачей, `office_qa`), поэтому замок файловый: `flock` на Linux,
    `msvcrt.locking` на Windows. Не дождались за LOCK_WAIT — Failed, а не
    второй экземпляр на том же профиле."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if not _TLOCK.acquire(timeout=LOCK_WAIT):
        raise Failed("Конвертер занят дольше %d с" % LOCK_WAIT)
    fh = None
    try:
        fh = open(str(profile_dir / ".soffice.lock"), "a+b")
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() - t0 > LOCK_WAIT:
                    raise Failed("Конвертер занят другим процессом дольше %d с" % LOCK_WAIT)
                time.sleep(0.5)
        yield
    finally:
        if fh is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()
        _TLOCK.release()


def convert(docx: bytes, profile_dir: Path, timeout: int = TIMEOUT, ext: str = ".docx") -> bytes:
    """.docx (или другой документ офиса, `ext`) → .pdf. Возвращает байты PDF.

    `profile_dir` — каталог ПОД НАШЕЙ записью (`backend/data/...`): туда
    ложится профиль LibreOffice и туда же смотрит HOME. Без этого конвертер
    под systemd не запускается вовсе и не говорит почему — просто висит
    до потолка по времени.
    """
    exe = binary()
    if not exe:
        raise NotAvailable(
            "PDF собирать нечем: на сервере нет LibreOffice. Установите его "
            "(apt install libreoffice-writer) или задайте SOFFICE_BIN. "
            "Формат .docx «как в оригинале» работает как работал.")
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Рабочий каталог — тоже под нашей записью: `PrivateTmp=true` даёт свой
    # /tmp, но полагаться на него нельзя, а `ProtectSystem=full` закрывает
    # остальное.
    ext = (ext or ".docx").lower()
    if not ext.startswith(".") or "/" in ext or "\\" in ext or len(ext) > 6:
        raise Failed("Неизвестный формат для печати")
    with _soffice_lock(profile_dir), tempfile.TemporaryDirectory(dir=str(profile_dir)) as tmp:
        tmp = Path(tmp)
        src = tmp / ("in" + ext)
        src.write_bytes(docx)
        env = dict(os.environ)
        env["HOME"] = str(profile_dir)
        cmd = [exe, "--headless", "--norestore",
               "-env:UserInstallation=file://" + str(profile_dir / "lo-profile").replace("\\", "/"),
               "--convert-to", FILTERS.get(ext, "pdf"),
               "--outdir", str(tmp), str(src)]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            raise Failed("Конвертер не ответил за %d с — файл слишком велик "
                         "или процесс завис." % timeout)
        except OSError as e:
            raise NotAvailable("Конвертер не запустился: %s" % e)
        out = tmp / "in.pdf"
        if not out.exists():
            why = (r.stderr or b"").decode("utf-8", "replace").strip()[:300]
            raise Failed("Конвертер не собрал PDF" + ((": " + why) if why else ""))
        data = out.read_bytes()
    if not data.startswith(b"%PDF"):
        raise Failed("Конвертер вернул не PDF")
    return data


if __name__ == "__main__":                      # ручная проверка на сервере
    print("конвертер:", binary() or "НЕ НАЙДЕН", file=sys.stderr)
