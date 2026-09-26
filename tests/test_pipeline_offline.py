"""Проверка пайплайна без сети.

Подменяем сборщики заранее записанными документами и убеждаемся, что:
  1. запрос проходит насквозь и возвращает карточки;
  2. формат карточки совпадает с тем, о чём договорились с интерфейсом;
  3. счётчики для дашборда считаются;
  4. кеш работает — второй вызов не ходит в сеть.

Запуск:
    python tests/test_pipeline_offline.py
"""

from __future__ import annotations

import pathlib
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.collect import arxiv, openalex  # noqa: E402
from src import pipeline  # noqa: E402

ТЕМЫ = [
    ("neuromorphic edge inference", "early prototype pilot deployment at two labs"),
    ("post quantum key exchange", "proof of concept implementation, preliminary results"),
    ("agent identity management", "experimental framework, feasibility study"),
    ("photonic interconnect fabric", "prototype demonstrated, early adoption at one vendor"),
    ("federated anomaly detection", "pilot study across three banks"),
    ("standard container orchestration", "widely adopted production-ready standard, market leader"),
]

ДОМЕНЫ = [
    ("https://arxiv.org/abs/", "препринт", "arXiv"),
    ("https://doi.org/10.1000/", "научная публикация", "Journal of Emerging Tech"),
    ("https://www.prnewswire.com/news-releases/", "пресс-релиз", "PR Newswire"),
]

ОРГАНИЗАЦИИ = ["MIT", "ETH Zurich", "Tsinghua University", "Fraunhofer", "Acme Labs"]


def сделать_документы(seed: int = 7, count: int = 48) -> list[dict]:
    """Небольшой набор документов, похожий на настоящий ответ API."""
    rnd = random.Random(seed)
    сегодня = date(2026, 9, 26)
    документы = []
    for i in range(count):
        тема, хвост = ТЕМЫ[i % len(ТЕМЫ)]
        префикс, тип, площадка = ДОМЕНЫ[i % len(ДОМЕНЫ)]
        дней_назад = rnd.choice([30, 90, 200, 300, 400, 600])
        уточнение = rnd.choice([
            "for industrial control loops", "in low-power sensor networks",
            "under adversarial conditions", "with hardware acceleration",
            "for real-time diagnostics", "in heterogeneous clusters",
        ])
        документы.append({
            "source_id": f"fixture:{i:03d}",
            "title": f"{тема} {уточнение} ({i})",
            "abstract": f"We present a {тема} approach {уточнение}. {хвост}.",
            "url": f"{префикс}{2600000 + i}",
            "published": (сегодня - timedelta(days=дней_назад)).isoformat(),
            "source_type": тип,
            "language": "en",
            "venue": площадка,
            "authors": [f"Author {i}"],
            "orgs": rnd.sample(ОРГАНИЗАЦИИ, rnd.randint(1, 3)),
            "domain": None,
            "trust": None,
            "translated": False,
            "ru_summary": None,
            "collected_at": "2026-09-26T12:00:00+00:00",
        })
    return документы


def main() -> int:
    документы = сделать_документы()
    половина = len(документы) // 2
    openalex.search = lambda query, limit=100: документы[:половина]
    arxiv.search = lambda query, limit=100: документы[половина:]

    запрос = "тестовый запрос про промышленные системы"
    карточки = pipeline.run(запрос, use_cache=False, save_to_db=False)

    assert карточки, "Пайплайн не вернул ни одной карточки"

    обязательные = {
        "technology", "area", "score", "top_features", "description",
        "advantage", "case_example", "sources", "verdict", "reject_reason",
    }
    for card in карточки:
        отсутствуют = обязательные - set(card)
        assert not отсутствуют, f"В карточке нет полей: {отсутствуют}"
        assert 0.0 <= card["score"] <= 1.0, "Скоринг вне диапазона"
        assert card["verdict"] in ("сигнал", "отклонено")
        if card["verdict"] == "отклонено":
            assert card["reject_reason"] in ("зрелая", "хайп", "шум")
        for источник in card["sources"]:
            for поле in ("title", "url", "published", "source_type", "language", "trust"):
                assert поле in источник, f"У источника нет поля {поле}"

    сигналы = [c for c in карточки if c["verdict"] == "сигнал"]
    отклонённые = [c for c in карточки if c["verdict"] == "отклонено"]
    assert len(сигналы) <= pipeline.TOP_N, "Сигналов больше пятнадцати"

    счётчики = pipeline.stats(карточки)
    assert счётчики["обработано_источников"] > 0

    # Второй вызов должен прийти из кеша — сборщики роняем нарочно.
    openalex.search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("сети нет"))
    arxiv.search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("сети нет"))
    из_кеша = pipeline.run(запрос, use_cache=True, save_to_db=False)
    assert len(из_кеша) == len(карточки), "Кеш вернул не то, что сохранил"

    print("Карточек всего:", len(карточки))
    print("Сигналов:", len(сигналы), "| отклонено:", len(отклонённые))
    print("Счётчики:", счётчики)
    print("Топ-5:")
    for card in сигналы[:5]:
        предикторы = ", ".join(f"{p['direction']}{p['name']}" for p in card["top_features"])
        print(f"  {card['score']:.2f}  {card['technology']}  [{предикторы}]")
    print("Причины отклонения:", {c["reject_reason"] for c in отклонённые})
    print("\nВсе проверки прошли.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
