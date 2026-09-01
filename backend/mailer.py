"""Отправка писем (подтверждение почты, восстановление пароля).

SMTP берётся из окружения; библиотек не добавляем — `smtplib` есть в stdlib.
Настроек нет — письмо НЕ отправляется, а печатается в журнал сервиса, и
`configured()` отвечает False. Это осознанно и видно снаружи: регистрация
в таком режиме сообщает человеку, что письмо не ушло, вместо того чтобы
показать «проверьте почту» и оставить его ждать письма, которого не будет.

Переменные: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD,
SMTP_SSL (1 — сразу TLS, иначе STARTTLS), MAIL_FROM, MAIL_FROM_NAME.
"""
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formataddr


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def configured() -> bool:
    return bool(_env("SMTP_HOST") and mail_from())


def mail_from() -> str:
    return _env("MAIL_FROM") or _env("SMTP_USER")


def send(to: str, subject: str, body: str) -> bool:
    """True — письмо принято сервером; False — почта не настроена или отказ.
    Исключения наружу не летят: письмо не должно ронять регистрацию, но и
    молчать о неудаче нельзя — ответ False и строка в журнале."""
    if not configured():
        print(f"[mail] SMTP не настроен — письмо для {to} НЕ отправлено:\n"
              f"       {subject}\n       {body}", file=sys.stderr)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((_env("MAIL_FROM_NAME", "CAT Translator"), mail_from()))
    msg["To"] = to
    msg.set_content(body)
    host, port = _env("SMTP_HOST"), int(_env("SMTP_PORT", "587") or 587)
    user, password = _env("SMTP_USER"), _env("SMTP_PASSWORD")
    ssl = _env("SMTP_SSL").lower() in ("1", "true", "yes", "on")
    try:
        if ssl:
            srv = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            srv = smtplib.SMTP(host, port, timeout=20)
        with srv:
            if not ssl:
                try:
                    srv.starttls()
                except Exception as e:
                    print(f"[mail] STARTTLS не поднялся: {e}", file=sys.stderr)
            if user:
                srv.login(user, password)
            srv.send_message(msg)
        return True
    except Exception as e:
        print(f"[mail] письмо для {to} не отправлено: {e}", file=sys.stderr)
        return False
