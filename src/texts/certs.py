"""Корневой сертификат НУЦ Минцифры для обращений к GigaChat.

Зачем это нужно. Домены Сбера (`ngw.devices.sberbank.ru`,
`gigachat.devices.sberbank.ru`) подписаны российским корневым центром
сертификации НУЦ Минцифры. Его нет ни в системном хранилище macOS, ни в
пакете `certifi`, которым пользуется `requests`, поэтому запрос падает:

    SSLCertVerificationError: self-signed certificate in certificate chain

Правильное решение — добавить корневой сертификат в доверенные, а не
отключать проверку. `verify=False` здесь недопустим: он выключает проверку
подлинности сервера целиком, то есть мы перестаём понимать, с кем вообще
разговариваем, и отправляем ключ авторизации кому попало.

Откуда берётся файл. Сертификат публичный, лежит на gosuslugi.ru
(`https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt`).
Скачивается скриптом `scripts/install_ru_certs.sh` в `certs/` и кладётся
в репозиторий: без него стенд и жюри при развёртывании получат ту же ошибку.

Как выбирается бандл:

1. `GIGACHAT_CA_BUNDLE` — если задан, берём указанный файл как есть;
2. `certs/russian_trusted_ca.pem` в корне репозитория;
3. ничего не нашли — возвращаем None, `requests` работает как обычно,
   в лог уходит понятное предупреждение.

В случаях 1 и 2 файл склеивается с бандлом `certifi` в один временный файл.
Это важно: `verify=<файл>` заменяет хранилище доверия целиком, и бандл из
одного российского корня сломал бы проверку всех остальных хостов.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CERT_DIR = ROOT / "certs"
RU_CERT = CERT_DIR / "russian_trusted_ca.pem"
COMBINED = CERT_DIR / "_bundle.pem"

DOWNLOAD_URL = "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"

_предупредили = False


def ru_cert_path() -> Path | None:
    """Путь к российскому сертификату или None, если его нет."""
    заданный = (os.getenv("GIGACHAT_CA_BUNDLE") or "").strip()
    if заданный:
        путь = Path(заданный).expanduser()
        if путь.is_file():
            return путь
        log.warning("GIGACHAT_CA_BUNDLE указывает на %s, файла нет", путь)
    if RU_CERT.is_file():
        return RU_CERT
    return None


def ca_bundle() -> str | None:
    """Файл для параметра `verify` в requests. None — доверяем системному.

    Склеенный бандл кешируется в `certs/_bundle.pem` и пересобирается,
    если исходный сертификат новее.
    """
    global _предупредили

    исходный = ru_cert_path()
    if исходный is None:
        if not _предупредили:
            log.warning(
                "Сертификат НУЦ Минцифры не найден. Обращения к GigaChat упадут "
                "на проверке TLS. Скачайте его: bash scripts/install_ru_certs.sh"
            )
            _предупредили = True
        return None

    try:
        import certifi
    except ImportError:
        # certifi нет — отдаём российский корень как есть. Для доменов Сбера
        # этого достаточно, на остальные хосты этот бандл не подставляется.
        return str(исходный)

    основной = Path(certifi.where())
    свежий = (
        COMBINED.is_file()
        and COMBINED.stat().st_mtime >= исходный.stat().st_mtime
        and COMBINED.stat().st_mtime >= основной.stat().st_mtime
    )
    if свежий:
        return str(COMBINED)

    try:
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        COMBINED.write_text(
            основной.read_text(encoding="utf-8").rstrip()
            + "\n\n# НУЦ Минцифры, добавлен для доменов Сбера\n"
            + исходный.read_text(encoding="utf-8").strip()
            + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        # Файловая система только для чтения (бывает в контейнерах) —
        # отдаём российский корень напрямую.
        log.info("Не удалось собрать общий бандл (%s), используем %s", error, исходный)
        return str(исходный)

    log.info("Бандл сертификатов собран: %s", COMBINED)
    return str(COMBINED)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    путь = ca_bundle()
    print("Бандл:", путь or "системный (российского корня нет)")
    if путь:
        import requests

        for url in (
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            "https://gigachat.devices.sberbank.ru/api/v1/models",
        ):
            try:
                ответ = requests.get(url, verify=путь, timeout=20)
                print(f"{url} -> TLS в порядке, код {ответ.status_code}")
            except requests.exceptions.SSLError as error:
                print(f"{url} -> TLS не прошёл: {error}")
            except requests.exceptions.RequestException as error:
                print(f"{url} -> сеть: {type(error).__name__} (TLS при этом мог пройти)")
