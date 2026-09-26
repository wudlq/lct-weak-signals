"""Хранилище документов и кандидатов.

Работает на SQLite из стандартной библиотеки — ставить ничего не нужно.
Схема лежит в schema.sql и написана переносимо: её можно без правок
применить к PostgreSQL, если появится время поднять его в docker-compose.
"""

from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "signals.db"
SCHEMA_FILE = pathlib.Path(__file__).with_name("schema.sql")

LIST_SEPARATOR = " | "


def connect(path: pathlib.Path | str | None = None) -> sqlite3.Connection:
    """Открывает базу и создаёт таблицы, если их ещё нет."""
    db_path = pathlib.Path(path or DEFAULT_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    connection.commit()
    return connection


def init_db(path: pathlib.Path | str | None = None) -> None:
    """Создать пустую базу. Вызывается один раз при развёртывании."""
    connection = connect(path)
    connection.close()
    log.info("База готова: %s", path or DEFAULT_DB)


def _pack(doc: dict[str, Any], query: str | None) -> tuple:
    """Документ -> строка таблицы. Списки складываем в текст через разделитель."""
    return (
        doc.get("source_id"),
        query,
        doc.get("title"),
        doc.get("abstract"),
        doc.get("url"),
        doc.get("published"),
        doc.get("source_type"),
        doc.get("language"),
        doc.get("venue"),
        LIST_SEPARATOR.join(doc.get("authors") or []),
        LIST_SEPARATOR.join(doc.get("orgs") or []),
        doc.get("domain"),
        doc.get("trust"),
        1 if doc.get("translated") else 0,
        doc.get("ru_summary"),
        doc.get("collected_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _unpack(row: sqlite3.Row) -> dict[str, Any]:
    """Строка таблицы -> документ в общем формате."""
    return {
        "source_id": row["source_id"],
        "title": row["title"],
        "abstract": row["abstract"],
        "url": row["url"],
        "published": row["published"],
        "source_type": row["source_type"],
        "language": row["language"],
        "venue": row["venue"],
        "authors": [a for a in (row["authors"] or "").split(LIST_SEPARATOR) if a],
        "orgs": [o for o in (row["orgs"] or "").split(LIST_SEPARATOR) if o],
        "domain": row["domain"],
        "trust": row["trust"],
        "translated": bool(row["translated"]),
        "ru_summary": row["ru_summary"],
        "collected_at": row["collected_at"],
    }


def save_docs(
    docs: Iterable[dict[str, Any]],
    query: str | None = None,
    path: pathlib.Path | str | None = None,
) -> int:
    """Сохраняет документы. Повторный source_id перезаписывается, дублей нет."""
    rows = [_pack(doc, query) for doc in docs]
    if not rows:
        return 0
    connection = connect(path)
    try:
        connection.executemany(
            """
            INSERT INTO documents (
                source_id, query, title, abstract, url, published, source_type,
                language, venue, authors, orgs, domain, trust, translated,
                ru_summary, collected_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
                query=excluded.query, title=excluded.title,
                abstract=COALESCE(excluded.abstract, documents.abstract),
                url=excluded.url, published=excluded.published,
                source_type=excluded.source_type, language=excluded.language,
                venue=excluded.venue, authors=excluded.authors, orgs=excluded.orgs,
                domain=excluded.domain, trust=excluded.trust,
                translated=excluded.translated,
                ru_summary=COALESCE(excluded.ru_summary, documents.ru_summary),
                collected_at=excluded.collected_at
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    log.info("Сохранено документов: %s", len(rows))
    return len(rows)


def load_docs(
    query: str | None = None,
    path: pathlib.Path | str | None = None,
) -> list[dict[str, Any]]:
    """Читает документы. Без запроса — всё, что есть в базе."""
    connection = connect(path)
    try:
        if query:
            cursor = connection.execute(
                "SELECT * FROM documents WHERE query = ? ORDER BY published DESC", (query,)
            )
        else:
            cursor = connection.execute("SELECT * FROM documents ORDER BY published DESC")
        return [_unpack(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def save_candidates(
    candidates: Iterable[dict[str, Any]],
    query: str,
    path: pathlib.Path | str | None = None,
) -> int:
    """Сохраняет карточки кандидатов целиком — интерфейс читает их отсюда."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        (
            f"{query}::{candidate.get('technology')}",
            query,
            candidate.get("technology"),
            candidate.get("area"),
            candidate.get("score"),
            candidate.get("verdict"),
            candidate.get("reject_reason"),
            json.dumps(candidate, ensure_ascii=False),
            now,
        )
        for candidate in candidates
    ]
    if not rows:
        return 0
    connection = connect(path)
    try:
        connection.executemany(
            """
            INSERT INTO candidates (
                candidate_id, query, technology, area, score, verdict,
                reject_reason, payload, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                score=excluded.score, verdict=excluded.verdict,
                reject_reason=excluded.reject_reason, payload=excluded.payload,
                created_at=excluded.created_at
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    return len(rows)


def load_candidates(query: str, path: pathlib.Path | str | None = None) -> list[dict[str, Any]]:
    """Карточки кандидатов по запросу, самые уверенные первыми."""
    connection = connect(path)
    try:
        cursor = connection.execute(
            "SELECT payload FROM candidates WHERE query = ? ORDER BY score DESC", (query,)
        )
        return [json.loads(row["payload"]) for row in cursor.fetchall()]
    finally:
        connection.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    тестовая_база = ROOT / "data" / "smoke.db"
    документ = {
        "source_id": "arxiv:2609.00001",
        "title": "Quantum sensing for edge devices",
        "abstract": "Короткая аннотация",
        "url": "https://arxiv.org/abs/2609.00001",
        "published": "2026-03-14",
        "source_type": "препринт",
        "language": "en",
        "venue": "arXiv",
        "authors": ["A. Author"],
        "orgs": ["MIT"],
        "domain": "arxiv.org",
        "trust": "высокий",
        "translated": False,
        "ru_summary": None,
        "collected_at": "2026-09-26T12:00:00+00:00",
    }
    save_docs([документ], query="quantum sensing", path=тестовая_база)
    назад = load_docs("quantum sensing", path=тестовая_база)
    print("прочитано:", len(назад), назад[0]["orgs"], назад[0]["trust"])
    тестовая_база.unlink(missing_ok=True)
