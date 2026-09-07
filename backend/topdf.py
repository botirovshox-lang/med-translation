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


def convert(docx: bytes, profile_dir: Path, timeout: int = TIMEOUT) -> bytes:
    """.docx → .pdf. Возвращает байты PDF.

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
    with tempfile.TemporaryDirectory(dir=str(profile_dir)) as tmp:
        tmp = Path(tmp)
        src = tmp / "in.docx"
        src.write_bytes(docx)
        env = dict(os.environ)
        env["HOME"] = str(profile_dir)
        cmd = [exe, "--headless", "--norestore",
               "-env:UserInstallation=file://" + str(profile_dir / "lo-profile").replace("\\", "/"),
               "--convert-to", "pdf:writer_pdf_Export",
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
