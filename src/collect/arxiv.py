"""Сборщик препринтов из arXiv.

Та же сигнатура и тот же формат на выходе, что у openalex.py — чтобы
пайплайн не знал, откуда пришёл документ.

arXiv отдаёт Atom XML и просит не бить чаще одного запроса в три секунды,
поэтому между страницами стоит пауза.

Запуск для проверки:
    python -m src.collect.arxiv "quantum sensing"
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from src.collect.trust import domain_of, domain_trust

log = logging.getLogger(__name__)

API_URL = "http://export.arxiv.org/api/query"
PAGE_SIZE = 100
TIMEOUT = 30
RETRIES = 3
RETRY_PAUSE = 3
POLITE_PAUSE = 3  # arXiv просит паузу между запросами
YEARS_BACK = 3

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    return " ".join(node.text.split())


def _entry_to_common_format(entry: ET.Element) -> dict[str, Any]:
    """Одна запись Atom -> общий формат документа."""
    raw_id = _text(entry.find("atom:id", NS)) or ""
    arxiv_id = raw_id.rsplit("/", 1)[-1]

    url = raw_id
    for link in entry.findall("atom:link", NS):
        if link.get("rel") == "alternate":
            url = link.get("href") or url

    published = _text(entry.find("atom:published", NS))
    if published:
        published = published[:10]  # из 2026-03-14T00:00:00Z берём дату

    authors: list[str] = []
    orgs: list[str] = []
    for author in entry.findall("atom:author", NS):
        name = _text(author.find("atom:name", NS))
        if name:
            authors.append(name)
        affiliation = _text(author.find("arxiv:affiliation", NS))
        if affiliation and affiliation not in orgs:
            orgs.append(affiliation)

    return {
        "source_id": f"arxiv:{arxiv_id}",
        "title": _text(entry.find("atom:title", NS)),
        "abstract": _text(entry.find("atom:summary", NS)),
        "url": url,
        "published": published,
        "source_type": "препринт",
        "language": "en",
        "venue": "arXiv",
        "authors": authors,
        "orgs": orgs,
        "domain": domain_of(url),
        "trust": domain_trust(url),
        "translated": False,
        "ru_summary": None,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _request(params: dict[str, Any]) -> str | None:
    """Запрос с тремя попытками. При неудаче возвращает None, но не падает."""
    pause = RETRY_PAUSE
    for attempt in range(1, RETRIES + 1):
        try:
            response = requests.get(API_URL, params=params, timeout=TIMEOUT)
            if response.status_code == 200:
                return response.text
            log.warning(
                "arXiv ответил %s, попытка %s из %s",
                response.status_code, attempt, RETRIES,
            )
        except requests.RequestException as error:
            log.warning("Сеть недоступна (%s), попытка %s из %s", error, attempt, RETRIES)
        time.sleep(pause)
        pause *= 2
    log.error("arXiv недоступен после %s попыток", RETRIES)
    return None


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """Разбирает Atom-ответ. Вынесено отдельно, чтобы тестировать без сети."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        log.warning("arXiv вернул неразбираемый XML: %s", error)
        return []
    return [_entry_to_common_format(entry) for entry in root.findall("atom:entry", NS)]


def search(query: str, limit: int = 100) -> list[dict[str, Any]]:
    """Ищет препринты по свободному запросу.

    Фильтр по дате arXiv в поиске не поддерживает, поэтому свежесть
    отсекаем уже после разбора ответа.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365 * YEARS_BACK)).date().isoformat()
    collected: list[dict[str, Any]] = []
    start = 0

    while len(collected) < limit:
        params = {
            "search_query": f"all:{query}",
            "start": start,
            "max_results": min(PAGE_SIZE, limit - len(collected)),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        body = _request(params)
        if not body:
            break

        batch = parse_feed(body)
        if not batch:
            break

        свежие = [d for d in batch if not d["published"] or d["published"] >= cutoff]
        collected.extend(свежие)

        # Если в пачке пошли старые записи — дальше только старее, выходим.
        if len(свежие) < len(batch):
            break

        start += len(batch)
        time.sleep(POLITE_PAUSE)

    log.info("arXiv: собрано %s записей по запросу %r", len(collected), query)
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
