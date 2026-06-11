"""
Скачивает все билингвальные PDF (EN/RU) с medlineplus.gov/languages/russian.html
в папку ./pdfs/
"""

import os
import re
import time
import json
import unicodedata
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin, urlparse

BASE_URL = "https://medlineplus.gov/languages/russian.html"
PDF_DIR = Path(__file__).parent / "pdfs"
INDEX_FILE = Path(__file__).parent / "pdf_index.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}
DELAY = 1.2  # секунд между запросами (вежливо к серверу)


def safe_filename(topic: str, lang: str = "RU") -> str:
    """Превращает название темы в безопасное имя файла (только ASCII)."""
    # Нормализуем и оставляем только ASCII буквы, цифры, пробелы, дефисы
    name = unicodedata.normalize("NFKD", topic)
    name = re.sub(r"[^\x20-\x7E]", "", name)  # только ASCII printable
    name = re.sub(r"[^\w\s-]", "", name).strip()
    name = re.sub(r"\s+", "_", name)
    return f"{name}_{lang}.pdf"


def get_pdf_url_from_page(url: str, session: requests.Session) -> str | None:
    """Если ссылка ведёт на промежуточную страницу — ищем прямой PDF-линк."""
    try:
        r = session.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        r.raise_for_status()
        # Если сервер вернул сам PDF
        if "application/pdf" in r.headers.get("Content-Type", ""):
            return url
        soup = BeautifulSoup(r.text, "lxml")
        # Ищем прямые ссылки на .pdf
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf"):
                return urljoin(url, href)
    except Exception as e:
        print(f"    [warn] Не удалось разобрать промежуточную страницу {url}: {e}")
    return None


def download_pdf(pdf_url: str, dest: Path, session: requests.Session) -> bool:
    """Скачивает PDF по URL в dest. Возвращает True если успешно."""
    try:
        r = session.get(pdf_url, headers=HEADERS, timeout=30, stream=True)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if "pdf" not in content_type and not pdf_url.lower().endswith(".pdf"):
            print(f"    [skip] Не PDF: {content_type}")
            return False
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        size_kb = dest.stat().st_size // 1024
        print(f"    [ok] {dest.name} ({size_kb} KB)")
        return True
    except Exception as e:
        print(f"    [error] {pdf_url}: {e}")
        return False


def collect_links(session: requests.Session) -> list[dict]:
    """Парсит главную страницу и возвращает список {'topic', 'href', 'source'}."""
    print(f"Загружаю {BASE_URL} ...")
    r = session.get(BASE_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    entries = []
    # Каждый топик — <li> внутри списка; ссылки рядом с "Bilingual PDF"
    for li in soup.select("li"):
        a_tags = li.find_all("a", href=True)
        for a in a_tags:
            text = a.get_text(" ", strip=True)
            # Ссылки вида "Bronchitis - Русский (Russian)"
            if "Русский" in text or "Russian" in text:
                full_text = li.get_text(" ", strip=True)
                if "Bilingual" not in full_text:
                    continue
                # Определяем источник (следующий элемент текста)
                source_span = li.find("span") or li.find(class_=True)
                source = source_span.get_text(strip=True) if source_span else ""
                # Берём только английскую часть до " - Русский"
                topic = text.split(" - ")[0].strip()
                entries.append({
                    "topic": topic,
                    "href": urljoin(BASE_URL, a["href"]),
                    "source": source,
                })
    print(f"Найдено {len(entries)} ссылок на билингвальные PDF")
    return entries


def run():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    links = collect_links(session)
    if not links:
        print("[!] Ничего не найдено. Возможно, изменилась структура страницы.")
        return

    index = []
    ok = 0
    skip = 0

    for i, entry in enumerate(links, 1):
        topic = entry["topic"]
        href = entry["href"]
        filename = safe_filename(topic)
        dest = PDF_DIR / filename

        print(f"[{i:03}/{len(links)}] {topic}")

        if dest.exists():
            print(f"    [cached] уже есть, пропускаю")
            index.append({**entry, "filename": filename, "status": "cached"})
            skip += 1
            continue

        # Проверяем: прямой PDF или промежуточная страница
        if href.lower().endswith(".pdf"):
            pdf_url = href
        else:
            time.sleep(DELAY)
            pdf_url = get_pdf_url_from_page(href, session)
            if not pdf_url:
                print(f"    [miss] PDF-ссылка не найдена на {href}")
                index.append({**entry, "filename": None, "status": "no_pdf_found"})
                continue

        time.sleep(DELAY)
        success = download_pdf(pdf_url, dest, session)
        status = "ok" if success else "error"
        index.append({
            **entry,
            "pdf_url": pdf_url,
            "filename": filename if success else None,
            "status": status,
        })
        if success:
            ok += 1

    # Сохраняем индекс
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n=== Готово: {ok} скачано, {skip} из кэша, {len(links)-ok-skip} не удалось ===")
    print(f"Индекс: {INDEX_FILE}")
    print(f"PDF:    {PDF_DIR}")


if __name__ == "__main__":
    run()
