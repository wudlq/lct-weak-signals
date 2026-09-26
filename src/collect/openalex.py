"""Сборщик научных публикаций из OpenAlex.

Возвращает документы в общем формате команды — тот же, что у arxiv.py.
Ключ берётся из переменной окружения OPENALEX_KEY, в коде его нет.

Запуск для проверки:
    python -m src.collect.openalex "quantum sensing"
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from src.collect.trust import domain_of, domain_trust

log = logging.getLogger(__name__)

API_URL = "https://api.openalex.org/works"
PAGE_SIZE = 100
TIMEOUT = 30
RETRIES = 3
RETRY_PAUSE = 3  # секунды, дальше удваивается

# Смотрим только свежее: слабый сигнал не может быть старой темой.
YEARS_BACK = 3


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """OpenAlex отдаёт аннотацию как индекс слов, а не текстом.

    Формат: {"слово": [позиции]}. Собираем обратно в строку.
    """
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for word, places in inverted.items():
        for place in places:
            positions.append((place, word))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def _pick_url(work: dict[str, Any]) -> str | None:
    """Ссылка на первоисточник: сначала DOI, потом страница журнала."""
    if work.get("doi"):
        return work["doi"]
    location = work.get("primary_location") or {}
    return location.get("landing_page_url") or work.get("id")


def _source_type(work: dict[str, Any]) -> str:
    """Препринт или научная публикация — важно для признака доверенности."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    if (source.get("type") or "").lower() == "repository":
        return "препринт"
    if (work.get("type") or "").lower() in {"preprint", "posted-content"}:
        return "препринт"
    return "научная публикация"


def _to_common_format(work: dict[str, Any]) -> dict[str, Any]:
    """Одна запись OpenAlex -> общий формат документа."""
    url = _pick_url(work)
    authorships = work.get("authorships") or []

    authors: list[str] = []
    orgs: list[str] = []
    for item in authorships:
        author = (item.get("author") or {}).get("display_name")
        if author:
            authors.append(author)
        for institution in item.get("institutions") or []:
            name = institution.get("display_name")
            if name and name not in orgs:
                orgs.append(name)

    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    openalex_id = (work.get("id") or "").rsplit("/", 1)[-1]

    return {
        "source_id": f"openalex:{openalex_id}",
        "title": work.get("display_name"),
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "url": url,
        "published": work.get("publication_date"),
        "source_type": _source_type(work),
        "language": work.get("language") or "en",
        "venue": source.get("display_name"),
        "authors": authors,
        "orgs": orgs,
        "domain": domain_of(url),
        "trust": domain_trust(url),
        "translated": False,
        "ru_summary": None,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _request(params: dict[str, Any]) -> dict[str, Any] | None:
    """Запрос с тремя попытками. При неудаче возвращает None, но не падает.

    Пайплайн должен продолжать работу, если один источник недоступен.
    """
    pause = RETRY_PAUSE
    for attempt in range(1, RETRIES + 1):
        try:
            response = requests.get(API_URL, params=params, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.json()
            if response.status_code in (429, 500, 502, 503, 504):
                log.warning(
                    "OpenAlex ответил %s, попытка %s из %s",
                    response.status_code, attempt, RETRIES,
                )
                time.sleep(pause)
                pause *= 2
                continue
            log.warning("OpenAlex ответил %s, дальше не пробуем", response.status_code)
            return None
        except requests.RequestException as error:
            log.warning("Сеть недоступна (%s), попытка %s из %s", error, attempt, RETRIES)
            time.sleep(pause)
            pause *= 2
    log.error("OpenAlex недоступен после %s попыток", RETRIES)
    return None


def search(query: str, limit: int = 100) -> list[dict[str, Any]]:
    """Ищет публикации по свободному запросу.

    Возвращает список документов в общем формате. Пустой список означает,
    что источник недоступен или ничего не найдено — это не ошибка.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=365 * YEARS_BACK)).date()
    collected: list[dict[str, Any]] = []
    cursor = "*"

    while len(collected) < limit:
        params: dict[str, Any] = {
            "search": query,
            "per-page": min(PAGE_SIZE, limit - len(collected)),
            "cursor": cursor,
            "filter": f"from_publication_date:{since.isoformat()}",
            "select": ",".join([
                "id", "doi", "display_name", "publication_date", "type",
                "language", "primary_location", "authorships",
                "abstract_inverted_index",
            ]),
        }
        key = os.getenv("OPENALEX_KEY")
        if key:
            params["api_key"] = key
        mail = os.getenv("OPENALEX_MAILTO")
        if mail:
            params["mailto"] = mail

        payload = _request(params)
        if not payload:
            break

        results = payload.get("results") or []
        if not results:
            break
        collected.extend(_to_common_format(work) for work in results)

        cursor = (payload.get("meta") or {}).get("next_cursor")
        if not cursor:
            break

    log.info("OpenAlex: собрано %s записей по запросу %r", len(collected), query)
    return collected[:limit]


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    запрос = sys.argv[1] if len(sys.argv) > 1 else "quantum sensing"
    документы = search(запрос, limit=20)
    print(f"Найдено: {len(документы)}")
    if документы:
        print(json.dumps(документы[0], ensure_ascii=False, indent=2))
