"""Приведение документов к одному виду и склейка дублей.

Один и тот же препринт часто приходит и из arXiv, и из OpenAlex.
Если не склеить, признак «рост публикаций» посчитается вдвое больше правды.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from src.collect.trust import LOW, MEDIUM, HIGH, domain_of, domain_trust

log = logging.getLogger(__name__)

# Поля общего формата. Если поля нет — ставим None, а не выбрасываем.
FIELDS = (
    "source_id", "title", "abstract", "url", "published", "source_type",
    "language", "venue", "authors", "orgs", "domain", "trust",
    "translated", "ru_summary", "collected_at",
)

TRUST_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2}

_SPACES = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def _clean_text(value: Any) -> str | None:
    """Убирает переносы и повторяющиеся пробелы."""
    if not value:
        return None
    text = _SPACES.sub(" ", str(value)).strip()
    return text or None


def _clean_date(value: Any) -> str | None:
    """Приводит дату к YYYY-MM-DD. Непонятную дату лучше потерять, чем соврать."""
    if not value:
        return None
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S%z", "%Y"):
        try:
            parsed = datetime.strptime(text[: len(pattern) + 6], pattern)
            return parsed.date().isoformat()
        except ValueError:
            continue
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    return match.group(0) if match else None


def normalize(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Дочищает поля и добивает недостающие. Порядок записей сохраняется."""
    result: list[dict[str, Any]] = []
    for doc in docs:
        item = {field: doc.get(field) for field in FIELDS}
        item["title"] = _clean_text(item["title"])
        item["abstract"] = _clean_text(item["abstract"])
        item["venue"] = _clean_text(item["venue"])
        item["published"] = _clean_date(item["published"])
        item["authors"] = list(item["authors"] or [])
        item["orgs"] = list(item["orgs"] or [])
        item["translated"] = bool(item["translated"])
        if not item["domain"]:
            item["domain"] = domain_of(item["url"])
        if not item["trust"]:
            item["trust"] = domain_trust(item["url"])
        if not item["title"]:
            continue  # запись без названия бесполезна и в выдаче, и в признаках
        result.append(item)
    return result


def _title_key(title: str) -> str:
    """Название в сравнимом виде: без знаков, в нижнем регистре."""
    return _SPACES.sub(" ", _NON_WORD.sub(" ", title.lower())).strip()


def _similar(left: str, right: str) -> float:
    """Схожесть названий от 0 до 1. rapidfuzz быстрее, difflib — запасной."""
    try:
        from rapidfuzz.fuzz import token_sort_ratio

        return token_sort_ratio(left, right) / 100
    except ImportError:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, left, right).ratio()


def _doi(url: str | None) -> str | None:
    """DOI из ссылки, если он там есть."""
    if not url:
        return None
    match = re.search(r"10\.\d{4,9}/\S+", url)
    return match.group(0).lower().rstrip(".,);") if match else None


def _better(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Из двух дублей оставляем тот, кому больше доверия, потом — где есть аннотация."""
    left_rank = (
        TRUST_ORDER.get(left.get("trust"), 0),
        1 if left.get("abstract") else 0,
        1 if left.get("orgs") else 0,
    )
    right_rank = (
        TRUST_ORDER.get(right.get("trust"), 0),
        1 if right.get("abstract") else 0,
        1 if right.get("orgs") else 0,
    )
    winner, loser = (left, right) if left_rank >= right_rank else (right, left)

    # Организации и авторов не теряем — они нужны признаку «число организаций».
    merged = dict(winner)
    merged["orgs"] = list(dict.fromkeys((winner.get("orgs") or []) + (loser.get("orgs") or [])))
    merged["authors"] = list(
        dict.fromkeys((winner.get("authors") or []) + (loser.get("authors") or []))
    )
    return merged


def _close_in_time(left: dict[str, Any], right: dict[str, Any], days: int = 180) -> bool:
    """Дубли выходят рядом по времени: препринт и статья расходятся на месяцы.

    Без этой проверки дедупликация схлопывает разные работы одной группы
    авторов с похожими названиями, и признак «рост публикаций» занижается.
    """
    a, b = left.get("published"), right.get("published")
    if not a or not b:
        return True
    try:
        left_date = datetime.strptime(a, "%Y-%m-%d").date()
        right_date = datetime.strptime(b, "%Y-%m-%d").date()
    except ValueError:
        return True
    return abs((left_date - right_date).days) <= days


def dedup(docs: list[dict[str, Any]], threshold: float = 0.90) -> list[dict[str, Any]]:
    """Склеивает дубли: сначала по DOI, потом по похожим названиям."""
    by_doi: dict[str, dict[str, Any]] = {}
    без_doi: list[dict[str, Any]] = []

    for doc in docs:
        doi = _doi(doc.get("url"))
        if doi:
            by_doi[doi] = _better(by_doi[doi], doc) if doi in by_doi else doc
        else:
            без_doi.append(doc)

    оставшиеся: list[tuple[str, dict[str, Any]]] = []
    for doc in list(by_doi.values()) + без_doi:
        key = _title_key(doc["title"])
        for index, (existing_key, existing) in enumerate(оставшиеся):
            if _similar(key, existing_key) >= threshold and _close_in_time(existing, doc):
                оставшиеся[index] = (existing_key, _better(existing, doc))
                break
        else:
            оставшиеся.append((key, doc))

    result = [doc for _, doc in оставшиеся]
    if len(result) < len(docs):
        log.info("Дедупликация: было %s, стало %s", len(docs), len(result))
    return result


def prepare(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Полный проход: нормализация плюс склейка дублей."""
    return dedup(normalize(docs))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    пример = [
        {
            "source_id": "arxiv:2609.00001",
            "title": "Quantum  sensing   for edge devices",
            "url": "https://arxiv.org/abs/2609.00001",
            "published": "2026-03-14T00:00:00Z",
            "abstract": None,
            "orgs": ["MIT"],
        },
        {
            "source_id": "openalex:W1",
            "title": "Quantum sensing for edge devices!",
            "url": "https://doi.org/10.1000/xyz123",
            "published": "2026-03-14",
            "abstract": "Полный текст аннотации",
            "orgs": ["ETH"],
        },
    ]
    итог = prepare(пример)
    print(f"было {len(пример)}, стало {len(итог)}")
    print(итог[0]["source_id"], итог[0]["orgs"], итог[0]["trust"])
