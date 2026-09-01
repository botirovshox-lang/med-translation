"""Тексты писем на языке ПОЛУЧАТЕЛЯ.

Почему отдельным файлом и почему только письма. Внутри бэкенда русский —
рабочий язык намеренно: его строки лежат в боевых данных (`_repair_findings`
разбирает `backcheck.reasons` подстрокой), промпты версионированы, а
`REPAIR_RECHECK_FAILED` сверяется с тем, что уже записано в проектах.
Переводить это значит ломать логику и данные. Поэтому весь интерфейс
переводится на ГРАНИЦЕ показа, в браузере.

Письмо — единственное, что уходит от сервера человеку МИМО браузера:
подставить перевод на границе некому. Зато язык получателя известен точно
(`user["uiLang"]`), так что выбор делается здесь и один раз.

Нет языка в таблице — письмо уходит по-русски. Пустое письмо или письмо
на языке, которого человек не знает, хуже: код подтверждения он всё равно
не получит.
"""

TEXTS = {
    "ru": {
        "verify.subject": "{brand}: код подтверждения {code}",
        "verify.body": (
            "Код подтверждения почты: {code}\n\n"
            "Он действует {minutes} минут. Если вы не заводили учётную запись "
            "в «{brand}», просто не отвечайте на это письмо."
        ),
        "reset.subject": "{brand}: код для смены пароля {code}",
        "reset.body": (
            "Код для смены пароля: {code}\n\n"
            "Он действует {minutes} минут. Если вы не просили менять пароль, "
            "ничего делать не нужно — пароль останется прежним."
        ),
        "invite.subject": "{brand}: приглашение в команду «{team}»",
        "invite.body": (
            "{who} приглашает вас в команду «{team}».\n\n"
            "Войдите в «{brand}» и откройте «Профиль» — приглашение ждёт там, "
            "его можно принять или отклонить.\n\n"
            "Если вы не ждали приглашения, ничего делать не нужно."
        ),
    },
    "uz": {
        "verify.subject": "{brand}: tasdiqlash kodi {code}",
        "verify.body": (
            "Pochtani tasdiqlash kodi: {code}\n\n"
            "U {minutes} daqiqa amal qiladi. Agar «{brand}» tizimida hisob "
            "yaratmagan bo'lsangiz, bu xatga javob bermang."
        ),
        "reset.subject": "{brand}: parolni almashtirish kodi {code}",
        "reset.body": (
            "Parolni almashtirish kodi: {code}\n\n"
            "U {minutes} daqiqa amal qiladi. Agar parolni almashtirishni "
            "so'ramagan bo'lsangiz, hech narsa qilish shart emas — parol "
            "avvalgicha qoladi."
        ),
        "invite.subject": "{brand}: «{team}» jamoasiga taklif",
        "invite.body": (
            "{who} sizni «{team}» jamoasiga taklif qilmoqda.\n\n"
            "«{brand}» tizimiga kiring va «Profil» bo'limini oching — taklif "
            "o'sha yerda turibdi, uni qabul qilish yoki rad etish mumkin.\n\n"
            "Agar taklif kutmagan bo'lsangiz, hech narsa qilish shart emas."
        ),
    },
}

DEFAULT = "ru"


def text(lang: str, key: str, **fields) -> str:
    table = TEXTS.get((lang or "").lower()) or TEXTS[DEFAULT]
    tpl = table.get(key) or TEXTS[DEFAULT].get(key) or ""
    try:
        return tpl.format(**fields)
    except Exception:
        # Кривой шаблон не должен отменять письмо: код нужен человеку сейчас.
        return tpl
