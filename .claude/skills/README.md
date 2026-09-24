# Навыки маркетинга и SEO (сторонние, MIT)

Взяты 24.09.2026 из открытых репозиториев без изменений (папки `evals/` убраны).
Общий контекст о продукте, который читают навыки marketingskills, —
`.agents/product-marketing.md` (обновлять навыком `/product-marketing`).
Правила правки лендинга — CLAUDE.md, раздел про `landing/`.

| Навык | Источник | Зачем нам |
|---|---|---|
| product-marketing | coreyhaines31/marketingskills @5b2c000 | общий контекст продукта для остальных навыков |
| seo-audit | — " — | аудит лендинга (у нас не было) |
| ai-seo | — " — | попадание в ответы ChatGPT/Perplexity/Алисы |
| programmatic-seo | — " — | страницы по парам языков и форматам (кластеры Б, В ядра) |
| competitors | — " — | страницы «vs Google Переводчик / DeepL / бюро» |
| copywriting, cro | — " — | тексты и конверсия лендинга |
| signup, onboarding | — " — | путь «регистрация → первый файл» |
| emails | — " — | письма после регистрации (`backend/mail_texts.py`) |
| referrals | — " — | программа приглашений (инвариант 36) |
| pricing | — " — | тарифы Старт / Профи / Издательство |
| analytics | — " — | события Метрики, воронка |
| content-strategy | — " — | блога нет — план контента |
| directory-submissions | — " — | каталоги ради ссылок новому домену |
| free-tools | — " — | бесплатный инструмент (напр. счётчик страниц файла) |
| site-architecture | — " — | структура лендинга при росте страниц |
| launch | — " — | план запуска |
| geo-citability, geo-crawlers, geo-llmstxt | zubair-trabzada/geo-seo-claude @b530c12 | цитируемость ИИ, доступ ИИ-ботов в robots.txt, проверка `llms.txt` |
| seo-hreflang | AgriciDaniel/claude-seo @e77e783 | проверка hreflang трёх языков лендинга |
| keyword-research | nowork-studio/notfair-plugin @d48eb24 | семантика (без ключей; частоты — Wordstat руками) |

Не взяты и почему: реклама Meta/Google (есть `SMM AI/ai-ads-agent`), блог-движок
claude-blog (блога нет), дубли тех же навыков в ai-marketing-claude,
aaron-marketing-skills, ai-marketing-skills, notfair; навыки, требующие платных
API (Ahrefs, DataForSEO, SE Ranking) или скриптов-коннекторов.
Ни один взятый навык не запускает сторонних скриптов и не требует ключей.
Помнить: у нас Яндекс важнее Google, а навыки написаны под Google.
