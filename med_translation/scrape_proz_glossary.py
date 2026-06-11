"""
Scrape medical glossaries from ProZ.com
- Medical: Health Care (8 pages)
- Medical: General (49 pages)

Parsing glossary pages to extract RU → EN term pairs
"""

import sys
import json
import time
import re
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Need: pip install requests beautifulsoup4")
    sys.exit(1)

sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = Path(r"C:\Users\Shox\med_translation\qa_output")
OUTPUT_DIR.mkdir(exist_ok=True)

GLOSSARIES = {
    "medical_healthcare": {
        "url": "https://www.proz.com/glossary-translations/russian-to-english-translations/medical-health-care",
        "pages": 8,
    },
    "medical_general": {
        "url": "https://www.proz.com/glossary-translations/russian-to-english-translations/medical-general",
        "pages": 49,
    }
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

all_pairs = []

print("=" * 80)
print("PROZ.COM GLOSSARY SCRAPER")
print("=" * 80)

for glossary_name, glossary_info in GLOSSARIES.items():
    print(f"\n[{glossary_name}] Scraping {glossary_info['pages']} pages...")

    for page_num in range(1, glossary_info['pages'] + 1):
        # ProZ.com URL structure: ?page=X
        url = f"{glossary_info['url']}?page={page_num}"

        print(f"  Page {page_num}/{glossary_info['pages']}...", end="", flush=True)

        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # ProZ glossaries have glossary entries in a table/list format
            # Look for entries with RU (source) and EN (target) columns
            # The page structure might vary, but typically entries are in divs or table rows

            # Try to find glossary entries (ProZ uses various HTML structures)
            entries = soup.find_all(class_=re.compile("glossary|entry|term", re.I))

            if not entries:
                # Alternative: look for td or divs with term/definition pattern
                entries = soup.find_all(["tr", "div"], class_=re.compile("row|term|item", re.I))

            if not entries:
                # Fallback: look for any text that looks like a glossary pair
                # ProZ structure might be: <td>Russian term</td><td>English term</td>
                rows = soup.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        ru_text = cells[0].get_text(strip=True)
                        en_text = cells[1].get_text(strip=True)

                        # Basic validation
                        if len(ru_text) > 2 and len(en_text) > 2:
                            # Check if Russian side looks like Cyrillic
                            if re.search(r"[А-Яа-яЁё]", ru_text):
                                all_pairs.append({
                                    "source": ru_text,
                                    "target": en_text,
                                    "source_glossary": glossary_name,
                                    "source_page": page_num,
                                })

            print(f" ✓")
            time.sleep(1)  # Polite delay

        except Exception as e:
            print(f" ✗ {e}")
            continue

print(f"\n{'='*80}")
print(f"Scraped {len(all_pairs):,} pairs")
print(f"{'='*80}")

# Save to JSON
output_file = OUTPUT_DIR / "proz_glossary.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(all_pairs, f, ensure_ascii=False, indent=2)
print(f"\n✓ Saved to {output_file}")

# Also save as TSV for easier inspection
output_tsv = OUTPUT_DIR / "proz_glossary.tsv"
import csv
with open(output_tsv, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["source", "target", "source_glossary", "source_page"], delimiter="\t")
    writer.writeheader()
    for pair in all_pairs:
        writer.writerow(pair)
print(f"✓ Saved to {output_tsv}")

if all_pairs:
    print(f"\nSample pairs:")
    for p in all_pairs[:5]:
        print(f"  {p['source']} → {p['target']}")
