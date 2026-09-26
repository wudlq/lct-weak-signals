"""Языковые модели, разрешённые ТЗ, за одним общим интерфейсом.

ТЗ разрешает: YandexGPT Lite 5 и Pro 5/5.1, Qwen3.6 35B-A3B и Qwen3 235B,
GigaChat 2 Lite/Pro/Max, gpt-4.1, gpt-5.6-luna. Передача запросов во
внешние сервисы вроде OpenRouter без согласования запрещена, поэтому
здесь только прямые адреса поставщиков.

ТЗ также требует «обязательное раскрытие формата выбора модели для
конкретного ответа и явное логирование». Поэтому каждый ответ возвращает
не только текст, но и имя модели, которая его дала, — оно уезжает
в карточку и видно в интерфейсе.

Какой поставщик используется, задаётся переменной LLM_PROVIDER:
    gigachat | yandex | openai | mock
Ключи берутся из переменных окружения, в коде их нет.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Protocol

import requests

log = logging.getLogger(__name__)

TIMEOUT = 60
RETRIES = 2


@dataclass
class Answer:
    """Ответ модели плюс её имя — для логирования и для интерфейса."""

    text: str
    model: str


class Provider(Protocol):
    name: str

    def complete(self, system: str, prompt: str) -> Answer:
        ...


class MockProvider:
    """Заглушка для тестов: возвращает заранее заданный ответ, в сеть не ходит."""

    name = "mock"
    unavailable: str | None = None

    def __init__(self, canned: str = "{}") -> None:
        self.canned = canned
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str) -> Answer:
        self.calls.append((system, prompt))
        return Answer(text=self.canned, model="mock")


class GigaChatProvider:
    """GigaChat 2. Ключ авторизации в GIGACHAT_AUTH_KEY, модель в GIGACHAT_MODEL.

    Домены Сбера подписаны корневым сертификатом НУЦ Минцифры, которого нет
    в системном хранилище. Путь к нему даёт `src.texts.certs.ca_bundle()` —
    подробности там же. Проверка TLS не отключается ни при каких условиях.
    """

    name = "gigachat"
    AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    def __init__(self) -> None:
        from src.texts.certs import ca_bundle

        self.auth_key = os.environ["GIGACHAT_AUTH_KEY"]
        self.model = os.getenv("GIGACHAT_MODEL", "GigaChat-2-Pro")
        self.verify: str | bool = ca_bundle() or True
        self.unavailable: str | None = None
        self._token: str | None = None
        self._expires: float = 0.0

    def _выключить(self, причина: str) -> None:
        """Больше не ходим в сеть до конца прогона.

        Без этого одна и та же ошибка авторизации повторяется на каждом из
        полутора десятков обращений к модели за прогон, по две попытки на
        каждое: лог превращается в простыню, а запрос — в минуты ожидания.
        """
        if self.unavailable is None:
            self.unavailable = причина
            log.error("GigaChat отключён до конца прогона: %s", причина)

    def _access_token(self) -> str:
        if self.unavailable:
            raise RuntimeError(self.unavailable)
        if self._token and time.time() < self._expires - 60:
            return self._token
        try:
            response = requests.post(
                self.AUTH_URL,
                headers={
                    "Authorization": f"Basic {self.auth_key}",
                    "RqUID": os.getenv(
                        "GIGACHAT_RQUID", "00000000-0000-0000-0000-000000000001"
                    ),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")},
                timeout=TIMEOUT,
                verify=self.verify,
            )
        except requests.exceptions.SSLError as error:
            self._выключить(
                "не проходит проверка сертификата. Нужен корневой сертификат НУЦ "
                "Минцифры: bash scripts/install_ru_certs.sh. "
                f"Исходная ошибка: {error}"
            )
            raise
        if response.status_code in (401, 403):
            self._выключить(
                f"ключ авторизации не принят (код {response.status_code}). "
                "Проверьте GIGACHAT_AUTH_KEY и GIGACHAT_SCOPE."
            )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._expires = payload.get("expires_at", time.time() + 1500) / 1000
        return self._token

    def complete(self, system: str, prompt: str) -> Answer:
        response = requests.post(
            self.CHAT_URL,
            headers={"Authorization": f"Bearer {self._access_token()}"},
            verify=self.verify,
            json={
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        return Answer(text=text, model=self.model)


class YandexGPTProvider:
    """YandexGPT. Ключ в YANDEX_API_KEY, каталог в YANDEX_FOLDER_ID."""

    name = "yandex"
    unavailable: str | None = None
    URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    def __init__(self) -> None:
        self.api_key = os.environ["YANDEX_API_KEY"]
        self.folder = os.environ["YANDEX_FOLDER_ID"]
        self.model = os.getenv("YANDEX_MODEL", "yandexgpt/latest")

    def complete(self, system: str, prompt: str) -> Answer:
        uri = f"gpt://{self.folder}/{self.model}"
        response = requests.post(
            self.URL,
            headers={"Authorization": f"Api-Key {self.api_key}"},
            json={
                "modelUri": uri,
                "completionOptions": {"temperature": 0.2, "maxTokens": 2000},
                "messages": [
                    {"role": "system", "text": system},
                    {"role": "user", "text": prompt},
                ],
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        text = response.json()["result"]["alternatives"][0]["message"]["text"]
        return Answer(text=text, model=uri)


class OpenAIProvider:
    """gpt-4.1. Ключ в OPENAI_API_KEY."""

    name = "openai"
    unavailable: str | None = None
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self) -> None:
        self.api_key = os.environ["OPENAI_API_KEY"]
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1")

    def complete(self, system: str, prompt: str) -> Answer:
        response = requests.post(
            self.URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        return Answer(text=text, model=self.model)


PROVIDERS = {
    "gigachat": GigaChatProvider,
    "yandex": YandexGPTProvider,
    "openai": OpenAIProvider,
}


def get_provider() -> Provider | None:
    """Поставщик по переменной LLM_PROVIDER. None — значит работаем без модели."""
    name = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if not name or name == "none":
        return None
    if name == "mock":
        return MockProvider()
    factory = PROVIDERS.get(name)
    if not factory:
        log.warning("Неизвестный LLM_PROVIDER=%r, работаем без языковой модели", name)
        return None
    try:
        return factory()
    except KeyError as missing:
        log.warning("Для %s не задана переменная %s, работаем без модели", name, missing)
        return None


def ask_json(provider: Provider, system: str, prompt: str) -> tuple[dict, str]:
    """Спрашивает модель и разбирает ответ как JSON.

    Модели любят обрамлять JSON пояснениями, поэтому вырезаем фигурные скобки.
    При неудаче возвращаем пустой словарь — тексты просто не заполнятся,
    но выдача не сломается.
    """
    # Поставщик мог отключить себя из-за ошибки, которая от повтора не пройдёт
    # (сертификат, неверный ключ). Тогда молча работаем без модели.
    if getattr(provider, "unavailable", None):
        return {}, getattr(provider, "name", "unknown")

    последняя: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            answer = provider.complete(system, prompt)
        except Exception as error:  # сеть, лимиты, отказ поставщика
            if getattr(provider, "unavailable", None):
                return {}, getattr(provider, "name", "unknown")
            последняя = error
            log.warning("Модель недоступна (%s), попытка %s из %s", error, attempt, RETRIES)
            time.sleep(2 * attempt)
            continue

        text = answer.text.strip()
        начало, конец = text.find("{"), text.rfind("}")
        if начало == -1 or конец == -1:
            log.warning("Модель вернула не JSON, попытка %s из %s", attempt, RETRIES)
            continue
        try:
            return json.loads(text[начало : конец + 1]), answer.model
        except json.JSONDecodeError:
            log.warning("JSON не разобрался, попытка %s из %s", attempt, RETRIES)

    if последняя is not None:
        # Все попытки упали на сети. Одну случайную неудачу терпим, вторую
        # подряд — уже нет: за прогон модель спрашивают полтора десятка раз,
        # и повторять безнадёжный запрос значит только тянуть время.
        подряд = getattr(provider, "_подряд_упало", 0) + 1
        try:
            provider._подряд_упало = подряд  # type: ignore[attr-defined]
            if подряд >= 2 and getattr(provider, "unavailable", "нет") is None:
                provider.unavailable = (  # type: ignore[attr-defined]
                    f"сеть недоступна ({последняя})"
                )
                log.error(
                    "Модель не отвечает второй запрос подряд, отключаем её "
                    "до конца прогона: %s", последняя,
                )
        except AttributeError:
            pass
    else:
        try:
            provider._подряд_упало = 0  # type: ignore[attr-defined]
        except AttributeError:
            pass

    return {}, getattr(provider, "name", "unknown")
