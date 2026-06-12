# Деплой Medical CAT Translator на Render.com + домен Beget

**Время:** ~15 минут. **Цена:** 0 ₽ (free tier).

---

## ✅ Что получится

`https://med.yourdomain.ru` → ваш React-дизайн + FastAPI бэкенд, HTTPS включён, SSL автоматически продлевается. Деплой обновляется при каждом `git push origin main`.

---

## Шаг 1 · Регистрация на Render.com (2 мин)

1. Откройте https://render.com → **Get Started**
2. Войдите через **GitHub** (он у вас уже подключён к `botirovshox-lang/med-translation`)
3. Разрешите Render читать репозиторий

## Шаг 2 · Создание сервиса (3 мин)

1. Render Dashboard → **New +** → **Blueprint**
2. Выберите репо `botirovshox-lang/med-translation`
3. Render сам найдёт `render.yaml` и предложит создать `med-translation`
4. Нажмите **Apply** — сборка пойдёт автоматически (~5 мин)
5. После сборки придёт адрес: `https://med-translation-XXXX.onrender.com` — уже работает

## Шаг 3 · Переменные окружения (2 мин)

Render Dashboard → ваш сервис → **Environment** → добавьте:

| Переменная | Значение |
|---|---|
| `APP_PASSWORD` | ваш пароль для входа |
| `OPENAI_API_KEY` | `sk-...` (если хотите реальные GPT-переводы; иначе можно пропустить — будут демо-переводы) |
| `GOOGLE_TRANSLATE_API_KEY` | ключ Google (опционально) |

После сохранения сервис автоматически перезапустится.

## Шаг 4 · Привязка вашего домена Beget (5 мин)

### 4.1 В Render

Dashboard → сервис → **Settings** → **Custom Domains** → **Add Custom Domain** → введите `med.yourdomain.ru`

Render покажет CNAME-запись, что-то вроде:
```
CNAME: med-translation-XXXX.onrender.com
```

### 4.2 В панели Beget

1. https://cp.beget.com → **Домены и поддомены**
2. Найдите ваш домен → шестерёнка → **DNS-записи** (или **Управление зоной**)
3. **Добавить запись**:
   - Тип: `CNAME`
   - Subdomain: `med`
   - Значение: `med-translation-XXXX.onrender.com` (что показал Render)
   - TTL: 300
4. Сохраните

### 4.3 Дождаться

DNS пропагация: 5–30 мин. Проверить:
```bash
nslookup med.yourdomain.ru
```

Render автоматически выпустит SSL-сертификат, как только увидит правильную CNAME. После этого работает `https://med.yourdomain.ru`.

---

## ⚠️ Особенность free tier

Через **15 минут неактивности** сервис засыпает. Первый запрос после простоя — **~30 сек** на пробуждение, потом всё быстро. Если для команды переводчиков это не подходит, апгрейд на Starter — **$7/мес**, никогда не спит.

---

## 🔧 Если что-то пойдёт не так

| Симптом | Что делать |
|---|---|
| Build failed | Логи в Render → **Logs**. Чаще всего — забыли push последнего коммита |
| 502 Bad Gateway | Сервис ещё не запустился. Подождите 1 мин, обновите |
| CNAME не работает | Проверьте у Beget через `nslookup med.yourdomain.ru`. Должен указывать на `*.onrender.com` |
| Кнопка «Войти» не работает | Не задан `APP_PASSWORD` — поставьте в Environment |
| Перевод выдаёт `[GPT demo translation of #N]` | Не задан `OPENAI_API_KEY` — это ожидаемое поведение, заглушка |

---

## 🚀 После деплоя

Каждый `git push origin main` запускает автодеплой Render (~3-5 мин). Никаких ручных действий не нужно.

Если хотите — можно ещё:
- Прикрепить **Cloudflare** перед Render: будет кэш + анти-DDoS бесплатно
- Подключить **GitHub Actions** для тестов перед мерджем

---

## Альтернатива: Beget VPS (если free tier не устраивает)

Минимальный VPS у Beget — около **190 ₽/мес**. Полный гайд через `systemd + nginx + certbot` есть в нашей прошлой переписке (могу повторить как отдельный файл, если нужно).
