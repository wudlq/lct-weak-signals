"""Признаки, по которым система отличает слабый сигнал от всего остального.

Методология взята из разметки организаторов: в исходном датасете балл
складывается из стадии развития и тренда упоминаний. Мы считаем те же две
оси плюс шесть подпорок, которые помогают отделить хайп и шум.

Главная сложность: признаки нужно считать и на обучении (там у нас строки
таблицы), и на живом запросе (там у нас документы из OpenAlex и arXiv).
Поэтому и то и другое сначала превращается в один объект Profile, а признаки
считаются уже от него.
"""

from __future__ import annotations

import collections
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

import pandas as pd

from src.collect.trust import HIGH, domain_of, domain_trust

log = logging.getLogger(__name__)

FEATURE_NAMES = [
    "stage_score",
    "trend_score",
    "early_words_ratio",
    "maturity_words_ratio",
    "org_count",
    "top_org_share",
    "trusted_share",
    "media_only",
]

# Человеческие названия — их показываем в интерфейсе как ключевые предикторы.
FEATURE_LABELS = {
    "stage_score": "стадия развития",
    "trend_score": "динамика упоминаний",
    "early_words_ratio": "слова ранней стадии",
    "maturity_words_ratio": "признаки зрелости",
    "org_count": "число организаций",
    "top_org_share": "доля лидера",
    "trusted_share": "доля доверенных источников",
    "media_only": "только медиа, без науки",
}

EARLY_WORDS = (
    "prototype", "proof of concept", "poc", "pilot", "early stage", "preclinical",
    "proof-of-concept", "experimental", "prelimin", "feasibility", "stealth",
    "прототип", "пилот", "концепц", "исследован", "раннее внедрение", "испытан",
)

MATURITY_WORDS = (
    "standard", "iso ", "ieee", "consortium", "generally available",
    "enterprise-grade", "production-ready", "market leader", "widely adopted",
    "commodity", "de facto",
    "стандарт", "гост", "консорциум", "массов", "серийн", "промышленн внедрен",
    "лидер рынка", "общепринят",
)

SCIENTIFIC_TYPES = {"научная публикация", "препринт", "патент"}

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Profile:
    """Всё, что мы знаем про одну технологию-кандидата."""

    technology: str
    area: str = ""
    texts: list[str] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    orgs: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    stage_hint: str = ""   # текст стадии из таблицы, если он есть
    trend_hint: str = ""   # текст тренда из таблицы, если он есть

    @property
    def text(self) -> str:
        return " ".join(t for t in self.texts if t).lower()


# --- стадия и динамика -----------------------------------------------------

STAGE_LEVELS = (
    (("раннее внедрение", "ранние внедрен", "ранняя серия", "early adoption",
      "controlled availability", "коммерческ"), 3),
    (("пилот", "pilot"), 2),
    (("прототип", "poc", "proof of concept", "prototype"), 1),
    (("концепц", "исследован", "research", "concept"), 0),
)


def stage_from_text(text: str) -> float:
    """Стадия от 0 (исследование) до 3 (раннее внедрение).

    Если в тексте написано «Прототип/PoC → Пилот», берём более позднюю стадию:
    технология уже дошла до неё.
    """
    lowered = (text or "").lower()
    found = [level for words, level in STAGE_LEVELS if any(w in lowered for w in words)]
    return float(max(found)) if found else 1.5  # середина шкалы, когда непонятно


def trend_from_text(text: str) -> float:
    """Динамика от 0 (стабильно) до 2 (растёт быстро)."""
    lowered = (text or "").lower()
    if any(w in lowered for w in ("растёт быстро", "растет быстро", "кратн", "взрывн", "surge")):
        return 2.0
    if any(w in lowered for w in ("растёт", "растет", "growing", "рост")):
        return 1.0
    if any(w in lowered for w in ("стабильн", "плато", "снижа", "flat", "declin")):
        return 0.0
    return 1.0


def trend_from_dates(dates: Iterable[date], today: date | None = None) -> float:
    """Та же шкала, но по датам публикаций: последние 12 месяцев к предыдущим 12."""
    today = today or date.today()
    свежие = sum(1 for d in dates if (today - d).days <= 365)
    прошлые = sum(1 for d in dates if 365 < (today - d).days <= 730)
    if свежие == 0:
        return 0.0
    if прошлые == 0:
        return 2.0 if свежие >= 3 else 1.0
    ratio = свежие / прошлые
    if ratio >= 2.0:
        return 2.0
    if ratio >= 1.2:
        return 1.0
    return 0.0


# --- сборка профиля --------------------------------------------------------

def profile_from_row(row: dict[str, Any]) -> Profile:
    """Профиль из строки обучающей таблицы (positives.csv / negatives.csv)."""
    urls = [u.strip() for u in str(row.get("source_urls") or "").split("|") if u.strip()]
    companies = [c.strip() for c in re.split(r"[,;]", str(row.get("companies") or "")) if c.strip()]
    return Profile(
        technology=str(row.get("technology") or "").strip(),
        area=str(row.get("area") or "").strip(),
        texts=[
            str(row.get("technology") or ""),
            str(row.get("why") or ""),
            str(row.get("stage") or ""),
            str(row.get("trend") or ""),
        ],
        dates=[],
        orgs=companies,
        urls=urls,
        # Тип источника в таблице не указан — выводим его из домена.
        source_types=[
            "научная публикация" if domain_trust(u) == HIGH else "отраслевое медиа"
            for u in urls
        ],
        stage_hint=str(row.get("stage") or ""),
        trend_hint=str(row.get("trend") or ""),
    )


def profile_from_docs(technology: str, docs: list[dict[str, Any]], area: str = "") -> Profile:
    """Профиль из документов, найденных по живому запросу."""
    dates: list[date] = []
    for doc in docs:
        if doc.get("published"):
            try:
                dates.append(datetime.strptime(doc["published"], "%Y-%m-%d").date())
            except ValueError:
                pass

    orgs: list[str] = []
    for doc in docs:
        orgs.extend(doc.get("orgs") or [])

    return Profile(
        technology=technology,
        area=area,
        texts=[f"{doc.get('title') or ''} {doc.get('abstract') or ''}" for doc in docs],
        dates=dates,
        orgs=orgs,
        urls=[doc.get("url") or "" for doc in docs],
        source_types=[doc.get("source_type") or "" for doc in docs],
    )


# --- сами признаки ---------------------------------------------------------

def _word_ratio(text: str, words: Iterable[str]) -> float:
    """Доля вхождений слов из списка, нормированная на длину текста."""
    if not text:
        return 0.0
    hits = sum(text.count(word) for word in words)
    total = max(len(_WORD.findall(text)), 1)
    return min(hits / total * 100, 10.0)  # обрезаем выбросы, шкала остаётся читаемой


def features_of(profile: Profile) -> dict[str, float]:
    """Восемь чисел по одному кандидату."""
    text = profile.text

    # Стадия: если есть подсказка из таблицы — берём её, иначе читаем тексты.
    stage = stage_from_text(profile.stage_hint or text)

    # Динамика: по датам, когда они есть, иначе по словам.
    trend = trend_from_dates(profile.dates) if profile.dates else trend_from_text(
        profile.trend_hint or text
    )

    orgs = [o for o in profile.orgs if o]
    counter = collections.Counter(orgs)
    org_count = float(len(counter))
    top_org_share = (counter.most_common(1)[0][1] / len(orgs)) if orgs else 0.0

    urls = [u for u in profile.urls if u]
    trusted = sum(1 for u in urls if domain_trust(u) == HIGH)
    trusted_share = trusted / len(urls) if urls else 0.0

    научные = sum(1 for t in profile.source_types if t in SCIENTIFIC_TYPES)
    media_only = 1.0 if (profile.source_types and научные == 0) else 0.0

    return {
        "stage_score": stage,
        "trend_score": trend,
        "early_words_ratio": _word_ratio(text, EARLY_WORDS),
        "maturity_words_ratio": _word_ratio(text, MATURITY_WORDS),
        "org_count": org_count,
        "top_org_share": top_org_share,
        "trusted_share": trusted_share,
        "media_only": media_only,
    }


def build_features(profiles: list[Profile]) -> pd.DataFrame:
    """Таблица признаков: строка на кандидата, колонки в порядке FEATURE_NAMES."""
    rows = [features_of(p) for p in profiles]
    frame = pd.DataFrame(rows, columns=FEATURE_NAMES)
    frame.insert(0, "technology", [p.technology for p in profiles])
    frame.insert(1, "area", [p.area for p in profiles])
    return frame


if __name__ == "__main__":
    import pathlib

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    csv_path = pathlib.Path(__file__).resolve().parents[2] / "data" / "positives.csv"
    table = pd.read_csv(csv_path)
    профили = [profile_from_row(row) for row in table.to_dict("records")]
    признаки = build_features(профили)
    pd.set_option("display.width", 200)
    print(признаки.head(5).to_string(index=False))
    print()
    print(признаки[FEATURE_NAMES].describe().round(2).to_string())
