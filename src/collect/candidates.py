"""Выделение технологий-кандидатов языковой моделью.

Зачем это вместо частотных словосочетаний. Частотный способ по устройству
выдаёт именные группы, а не технологии: сначала лезли академические обороты
(«consistently outperforms»), потом зонтичные термины («machine learning»),
дальше полезли бы региональные. Каждый стоп-лист убирает конкретный мусор,
но метод так и не отличает технологию от частой пары слов.

Модель читает заголовки найденных документов и называет технологии, которые
в них обсуждаются. Это не противоречит ТЗ: запрещено формировать выдачу на
одних знаниях модели, а здесь она не придумывает ничего от себя — только
называет то, что есть в собранных документах, и каждый кандидат остаётся
привязан к конкретным публикациям со ссылками.

Если модель не настроена или ответила мусором, пайплайн откатывается на
частотный способ. Система работает без ключа, просто хуже.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

MAX_TITLES = 60          # больше в запрос не влезет без потери внимания модели
MAX_CANDIDATES = 25
MIN_DOCS_PER_CANDIDATE = 2

SYSTEM = (
    "Ты технологический аналитик. Читаешь заголовки научных работ и называешь "
    "конкретные технологии, которые в них обсуждаются. Ничего не добавляешь от "
    "себя: если технологии нет в заголовках, ты её не называешь. "
    "Отвечаешь строго одним объектом JSON без пояснений."
)

PROMPT = """Запрос пользователя: «{query}»

Заголовки найденных работ:
{titles}

Назови до {limit} конкретных технологий, методов или подходов, которые
обсуждаются в этих работах. Верни JSON:

{{"candidates": [
  {{"name_ru": "название по-русски",
    "name_en": "название как в оригинале",
    "docs": [номера заголовков, где эта технология обсуждается]}}
]}}

Требования:
- называй технологию, а не область: «квантово-устойчивая криптография», а не
  «кибербезопасность» и не «машинное обучение»;
- не называй то, что описывает саму работу: «сравнение подходов», «обзор»,
  «эксперимент» — это не технологии;
- не называй организации, университеты и страны;
- каждая технология должна встречаться минимум в двух заголовках;
- номера бери из списка выше, не придумывай."""


def _format_titles(documents: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{номер}. {doc.get('title') or ''}"
        for номер, doc in enumerate(documents[:MAX_TITLES], 1)
    )


def extract(
    documents: list[dict[str, Any]],
    query: str,
    provider: Any | None = None,
) -> list[dict[str, Any]]:
    """Кандидаты от модели.

    Возвращает список словарей: name_ru, name_en, docs.
    Пустой список означает, что модель недоступна или ответила негодно —
    вызывающий код должен откатиться на частотный способ.
    """
    if not documents:
        return []

    if provider is None:
        from src.texts.providers import get_provider

        provider = get_provider()
    if provider is None:
        log.info("Языковая модель не настроена, кандидатов выделяем частотно")
        return []

    from src.texts.providers import ask_json

    ответ, модель = ask_json(
        provider,
        SYSTEM,
        PROMPT.format(
            query=query,
            titles=_format_titles(documents),
            limit=MAX_CANDIDATES,
        ),
    )

    сырые = ответ.get("candidates") or []
    if not сырые:
        log.warning("Модель не вернула кандидатов, откатываемся на частотный способ")
        return []

    доступные = documents[:MAX_TITLES]
    кандидаты: list[dict[str, Any]] = []
    видели: set[str] = set()

    for item in сырые:
        name_ru = str(item.get("name_ru") or "").strip()
        name_en = str(item.get("name_en") or "").strip()
        if not name_ru and not name_en:
            continue

        ключ = (name_ru or name_en).lower()
        if ключ in видели:
            continue

        номера = item.get("docs") or []
        связанные = []
        for номер in номера:
            try:
                индекс = int(номер) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= индекс < len(доступные):
                связанные.append(доступные[индекс])

        # Модель любит придумывать номера. Кандидат без подтверждённых
        # документов — это ровно то, что ТЗ запрещает, поэтому выбрасываем.
        if len(связанные) < MIN_DOCS_PER_CANDIDATE:
            continue

        видели.add(ключ)
        кандидаты.append({
            "name_ru": name_ru or name_en,
            "name_en": name_en or name_ru,
            "docs": связанные,
            "model": модель,
        })

    log.info(
        "Модель %s выделила кандидатов: %s из %s предложенных",
        модель, len(кандидаты), len(сырые),
    )
    return кандидаты


if __name__ == "__main__":
    import json

    from src.texts.providers import MockProvider

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    документы = [
        {"title": "Post-quantum key exchange for constrained devices", "url": "u1"},
        {"title": "Lattice-based key exchange in embedded systems", "url": "u2"},
        {"title": "Confidential computing with hardware enclaves", "url": "u3"},
        {"title": "Enclave-based inference for private models", "url": "u4"},
    ]
    заготовка = json.dumps({
        "candidates": [
            {"name_ru": "Постквантовый обмен ключами",
             "name_en": "post-quantum key exchange", "docs": [1, 2]},
            {"name_ru": "Конфиденциальные вычисления в аппаратных анклавах",
             "name_en": "confidential computing", "docs": [3, 4]},
            {"name_ru": "Выдуманная технология",
             "name_en": "hallucinated", "docs": [99]},
        ]
    }, ensure_ascii=False)

    итог = extract(документы, "слабые сигналы в кибербезопасности",
                   provider=MockProvider(заготовка))
    for c in итог:
        print(f"{c['name_ru']} ({c['name_en']}) — документов: {len(c['docs'])}")
    print("Выдуманный кандидат отброшен:", all(c["name_en"] != "hallucinated" for c in итог))
