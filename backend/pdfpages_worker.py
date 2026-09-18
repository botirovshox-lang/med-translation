"""Дочерний процесс: текстовый слой диапазона страниц PDF — построчно.

Зачем отдельным процессом, а не потоком: извлечение текста pypdf — чистый
Python, и потоки упираются в GIL. Книга на 378 страниц читалась 31 с одним
ядром; четыре процесса делят её на куски, и ответ приходит вчетверо быстрее.
Библиотека та же (pypdf), поэтому строки те же буква в букву: правила
`pdftext` подобраны именно на её выдаче, и смена извлекателя (pdfium быстрее
ещё вдесятеро) поменяла бы переносы, колонтитулы и страницы-картинки.

Отдельным файлом, а не `multiprocessing`: тот при старте ребёнка импортирует
главный модуль родителя, а у воркера прогонов это `backend.worker` →
`main.py` — состояние, база, кэши. Здесь ребёнок знает только pypdf.

Протокол: байты PDF — на stdin; аргументы — start end; на stdout по строке
JSON на страницу: [номер, [строки]]. Ошибка — код возврата 1 и текст
в stderr: родитель тогда читает сам, по-старому."""

import io
import json
import sys


def main() -> int:
    start, end = int(sys.argv[1]), int(sys.argv[2])
    data = sys.stdin.buffer.read()
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore
    reader = PdfReader(io.BytesIO(data))
    out = sys.stdout
    for i in range(start, min(end, len(reader.pages))):
        lines = (reader.pages[i].extract_text() or "").splitlines()
        out.write(json.dumps([i, lines]) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                      # pragma: no cover
        sys.stderr.write("%s: %s\n" % (type(e).__name__, e))
        sys.exit(1)
