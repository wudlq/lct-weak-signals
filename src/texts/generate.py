"""Русские тексты для карточки: название, описание, преимущество, кейс.

Зачем это нужно. Кандидаты выделяются из заголовков и аннотаций OpenAlex
и arXiv, то есть приходят по-английски. ТЗ требует, чтобы интерфейс и вся
аналитическая выдача были на русском, а у зарубежного материала сохранялись
оригинальное название, ссылка, дата и язык, с пометкой об автопереводе.

Главное правило: языковая модель не придумывает факты. Ей на вход идут
только найденные документы, и каждое утверждение должно опираться на них.
ТЗ прямо запрещает формировать выдачу на одних знаниях языковой модели.
Всё, что модель не подтвердила ссылкой, остаётся пустым.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.texts.providers import Provider, ask_json, get_provider

log = logging.getLogger(__name__)

MAX_DOCS_IN_PROMPT = 5
MAX_ABSTRACT_CHARS = 700

SYSTEM = (
    "Ты аналитик технологических трендов. Работаешь только с теми документами, "
    "которые тебе дали. Ничего не добавляешь из своих знаний: если факта нет "
    "в документах, оставляешь поле пустым. Отвечаешь строго одним объектом JSON "
    "без пояснений до и после. Все тексты — на русском языке."
)

PROMPT = """Ниже документы, найденные по технологии «{technology}».

{documents}

Верни JSON с полями:
{{
  "technology_ru": "название технологии по-русски, до 90 знаков",
  "description": "что это за технология, 2-3 предложения, только по документам",
  "advantage": "какое преимущество даёт по сравнению с существующим, 1-2 предложения",
  "case_example": "кто уже пробует и что именно сделал, с указанием номера документа",
  "case_source": номер документа, на который опирается кейс, или null,
  "summaries": {{"1": "русское резюме документа 1 в одно предложение", "2": "..."}}
}}

Требования:
- если в документах нет данных для поля — поставь null, не выдумывай;
- в описании не используй слова, которых нет в документах, как названия компаний;
- кейс-пример обязан опираться на конкретный документ из списка;
- резюме нужны для всех документов, которые не на русском."""


def _format_documents(docs: list[dict[str, Any]]) -> str:
    """Документы в виде, который модель не перепутает."""
    куски = []
    for номер, doc in enumerate(docs, 1):
        аннотация = (doc.get("abstract") or "")[:MAX_ABSTRACT_CHARS]
        куски.append(
            f"Документ {номер}\n"
            f"Название: {doc.get('title')}\n"
            f"Дата: {doc.get('published') or 'не указана'}\n"
            f"Тип: {doc.get('source_type')}\n"
            f"Язык: {doc.get('language')}\n"
            f"Ссылка: {doc.get('url')}\n"
            f"Аннотация: {аннотация or 'нет'}"
        )
    return "\n\n".join(куски)


def _clean(value: Any, limit: int = 600) -> str | None:
    """Пустые значения модели приводим к None, а не к строке «null»."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "нет данных", "-"}:
        return None
    return text[:limit]


def describe(card: dict[str, Any], provider: Provider | None = None) -> dict[str, Any]:
    """Заполняет русские поля карточки. Карточку меняет на месте и возвращает.

    Без языковой модели карточка остаётся рабочей: название и описание
    берутся из документов как есть, а флаг technology_language говорит
    интерфейсу, что перевода нет.
    """
    docs = (card.get("sources") or [])[:MAX_DOCS_IN_PROMPT]
    if not docs:
        return card

    provider = provider or get_provider()
    if provider is None:
        card["description"] = _clean(docs[0].get("abstract"), limit=400)
        card["text_model"] = None
        log.info("Языковая модель не настроена, тексты оставлены как есть")
        return card

    ответ, модель = ask_json(
        provider,
        SYSTEM,
        PROMPT.format(
            technology=card.get("technology_original") or card.get("technology"),
            documents=_format_documents(docs),
        ),
    )

    card["text_model"] = модель  # ТЗ требует логировать, какая модель ответила

    название = _clean(ответ.get("technology_ru"), limit=90)
    if название:
        card["technology"] = название
        card["technology_language"] = "ru"

    card["description"] = _clean(ответ.get("description"))
    card["advantage"] = _clean(ответ.get("advantage"))

    # Кейс принимаем только с опорой на конкретный документ из списка.
    кейс = _clean(ответ.get("case_example"))
    номер = ответ.get("case_source")
    if кейс and isinstance(номер, (int, str)) and str(номер).isdigit():
        индекс = int(номер) - 1
        if 0 <= индекс < len(docs):
            card["case_example"] = кейс
            card["case_source_url"] = docs[индекс].get("url")
        else:
            card["case_example"] = None
            log.info("Кейс сослался на документ вне списка, отбрасываем")
    else:
        card["case_example"] = None

    # Русские резюме зарубежных источников плюс пометка об автопереводе.
    резюме = ответ.get("summaries") or {}
    for номер_дока, doc in enumerate(docs, 1):
        текст = _clean(резюме.get(str(номер_дока)), limit=300)
        if текст and (doc.get("language") or "en") != "ru":
            doc["ru_summary"] = текст
            doc["translated"] = True

    return card


def describe_all(
    cards: list[dict[str, Any]],
    limit: int | None = None,
    provider: Provider | None = None,
) -> list[dict[str, Any]]:
    """Тексты для списка карточек.

    По умолчанию обрабатываем только то, что попало в ТОП-15: на отклонённых
    кандидатах тексты не нужны, а лимиты языковой модели стоят денег.
    """
    provider = provider or get_provider()
    сигналы = [c for c in cards if c.get("verdict") == "сигнал"]
    цель = сигналы[: limit] if limit else сигналы
    for card in цель:
        try:
            describe(card, provider=provider)
        except Exception as error:  # одна неудачная карточка не ломает выдачу
            log.warning("Тексты для %r не собрались: %s", card.get("technology"), error)
    return cards


if __name__ == "__main__":
    from src.texts.providers import MockProvider

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    заготовка = json.dumps({
        "technology_ru": "Нейроморфный вывод на периферийных устройствах",
        "description": "Подход переносит вычисления нейросети на энергоэффективные "
                       "нейроморфные чипы рядом с датчиком.",
        "advantage": "Снижает задержку и потребление по сравнению с отправкой "
                     "данных в облако.",
        "case_example": "В документе 1 описан пилот на двух исследовательских "
                        "площадках.",
        "case_source": 1,
        "summaries": {"1": "Препринт описывает пилотное внедрение на двух площадках."},
    }, ensure_ascii=False)

    карточка = {
        "technology": "neuromorphic edge inference",
        "technology_original": "neuromorphic edge inference",
        "technology_language": "en",
        "verdict": "сигнал",
        "sources": [{
            "title": "Neuromorphic edge inference for industrial control loops",
            "published": "2026-05-01",
            "source_type": "препринт",
            "language": "en",
            "url": "https://arxiv.org/abs/2605.00001",
            "abstract": "We present a neuromorphic edge inference approach. Pilot at two labs.",
        }],
    }

    итог = describe(карточка, provider=MockProvider(заготовка))
    print("название:", итог["technology"], f"({итог['technology_language']})")
    print("оригинал:", итог["technology_original"])
    print("описание:", итог["description"])
    print("кейс:", итог["case_example"])
    print("ссылка кейса:", итог.get("case_source_url"))
    print("резюме источника:", итог["sources"][0]["ru_summary"])
    print("пометка о переводе:", итог["sources"][0]["translated"])
    print("модель:", итог["text_model"])
