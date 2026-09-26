"""Уровень доверенности источника по домену.

По ТЗ у каждого источника должен отображаться уровень доверенности.
Словарь доменов лежит в data/trust_domains.csv (колонки: domain,level).
Если домена нет в словаре — работают правила по умолчанию.
"""

from __future__ import annotations

import csv
import functools
import pathlib
from urllib.parse import urlparse

TRUST_FILE = pathlib.Path(__file__).resolve().parents[2] / "data" / "trust_domains.csv"

HIGH = "высокий"
MEDIUM = "средний"
LOW = "низкий"

# Доменные зоны, которым доверяем без отдельной записи в словаре:
# государственные органы, университеты и научные центры.
HIGH_SUFFIXES = (".gov", ".gov.ru", ".edu", ".ac.uk", ".edu.cn", ".int")

# Известные научные и патентные площадки.
HIGH_HOSTS = {
    "arxiv.org",
    "www.nature.com",
    "nature.com",
    "science.org",
    "www.science.org",
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "link.springer.com",
    "www.sciencedirect.com",
    "pubmed.ncbi.nlm.nih.gov",
    "patents.google.com",
    "patentsview.org",
    "www.mdpi.com",
    "openalex.org",
    "doi.org",
}

# Агрегаторы, ленты пресс-релизов и блоги — только как первичный индикатор.
LOW_HOSTS = {
    "www.prnewswire.com",
    "prnewswire.com",
    "www.businesswire.com",
    "businesswire.com",
    "medium.com",
    "substack.com",
    "finance.yahoo.com",
    "www.linkedin.com",
    "x.com",
    "twitter.com",
    "t.me",
    "habr.com",
    "vc.ru",
}


@functools.lru_cache(maxsize=1)
def _load_dictionary() -> dict[str, str]:
    """Читает словарь доменов. Файла может не быть — тогда работают правила."""
    table: dict[str, str] = {}
    if not TRUST_FILE.exists():
        return table
    with TRUST_FILE.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            domain = (row.get("domain") or "").strip().lower()
            level = (row.get("level") or "").strip().lower()
            if domain and level in (HIGH, MEDIUM, LOW):
                table[domain] = level
    return table


def domain_of(url: str | None) -> str:
    """Хост из ссылки, без www. Пустая строка, если ссылки нет."""
    if not url:
        return ""
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def domain_trust(url: str | None) -> str:
    """Уровень доверенности: высокий, средний или низкий.

    Порядок: словарь -> известные площадки -> доменная зона -> средний.
    Средний уровень по умолчанию, потому что незнакомый отраслевой сайт
    не повод считать источник мусорным, но и не повод верить ему как журналу.
    """
    host = domain_of(url)
    if not host:
        return LOW

    table = _load_dictionary()
    if host in table:
        return table[host]

    if host in LOW_HOSTS or f"www.{host}" in LOW_HOSTS:
        return LOW
    if host in HIGH_HOSTS or f"www.{host}" in HIGH_HOSTS:
        return HIGH
    if any(host.endswith(suffix) for suffix in HIGH_SUFFIXES):
        return HIGH

    return MEDIUM


def reset_cache() -> None:
    """Сбросить кеш словаря — нужно после того, как файл дополнили."""
    _load_dictionary.cache_clear()


if __name__ == "__main__":
    примеры = [
        "https://arxiv.org/abs/2609.01234",
        "https://www.prnewswire.com/news-releases/example",
        "https://mit.edu/news/example",
        "https://some-industry-media.tech/article",
        None,
    ]
    for url in примеры:
        print(f"{url} -> {domain_trust(url)}")
