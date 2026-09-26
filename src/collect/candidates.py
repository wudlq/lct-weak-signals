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
import math
import re
from typing import Any

log = logging.getLogger(__name__)

MAX_TITLES = 60          # больше в запрос не влезет без потери внимания модели
MAX_CANDIDATES = 25
MIN_DOCS_PER_CANDIDATE = 2
MIN_TOKEN_SHARE = 0.6    # какая доля слов названия должна найтись в документе

SYSTEM = (
    "Ты технологический аналитик. Читаешь заголовки научных работ и называешь "
    "конкретные технологии, которые в них обсуждаются. Ничего не добавляешь от "
    "себя: если технологии нет в заголовках, ты её не называешь. "
    "Отвечаешь строго одним объектом JSON без пояснений. "
    "Ключи в JSON пишешь латиницей ровно так, как они даны в примере."
)

PROMPT = """Запрос пользователя: «{query}»

Заголовки найденных работ:
{titles}

Назови до {limit} конкретных технологий, методов или подходов, которые
обсуждаются в этих работах. Верни JSON ровно с такими ключами:

{{"candidates": [
  {{"name_ru": "название по-русски",
    "name_en": "название как в оригинале",
    "docs": [номера заголовков, где эта технология обсуждается]}}
]}}

Требования:
- называй технологию, а не область: «квантово-устойчивая криптография», а не
  «кибербезопасность» и не «машинное обучение»;
- называй так, чтобы под название попадало несколько работ: не переписывай
  заголовок целиком, а назови технологию, о которой он написан;
- если несколько работ про одно и то же — это одна технология, перечисли все
  их номера в docs;
- не называй то, что описывает саму работу: «сравнение подходов», «обзор»,
  «эксперимент» — это не технологии;
- не называй организации, университеты и страны;
- номера бери из списка выше, не придумывай.

Примеры, которые не подходят, потому что это область, а не технология:
«искусственный интеллект в кибербезопасности», «машинное обучение для
обнаружения угроз», «оценка рисков», «обнаружение аномалий». Подходят:
«квантово-устойчивая подпись на решётках», «обнаружение аномалий в
зашифрованном трафике OPC UA», «нейро-символическая конфигурация
промышленных систем»."""

_TOKEN = re.compile(r"[a-zA-Z][\w\-]+")

# Служебные слова английских названий: по ним искать документы бессмысленно.
SKIP = {
    "and", "or", "of", "the", "for", "with", "in", "on", "to", "from", "via",
    "using", "based", "a", "an", "its", "their", "new", "novel", "toward",
    "towards", "approach", "approaches", "method", "methods", "technique",
    "techniques", "system", "systems", "model", "models",
}


def _sample(documents: list[dict[str, Any]], limit: int = MAX_TITLES) -> list[dict[str, Any]]:
    """Ровный срез по всему набору, а не первые N.

    Документы приходят сгруппированными по поисковым строкам, и первые
    шестьдесят — это почти целиком первая строка запроса. Модель тогда видит
    одну треть темы и остальные две не называет вовсе.
    """
    if len(documents) <= limit:
        return list(documents)
    шаг = len(documents) / limit
    return [documents[int(i * шаг)] for i in range(limit)]


def _format_titles(documents: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{номер}. {doc.get('title') or ''}"
        for номер, doc in enumerate(documents, 1)
    )


ИМЕНА_ПОЛЕЙ = ("name_ru", "name_en", "name", "название", "docs")


def _похоже_на_кандидатов(значение: Any) -> bool:
    return (
        isinstance(значение, list)
        and bool(значение)
        and any(
            isinstance(x, dict) and any(поле in x for поле in ИМЕНА_ПОЛЕЙ)
            for x in значение
        )
    )


def _найти_список(ответ: Any) -> tuple[list[Any], str]:
    """Достаёт список кандидатов, как бы модель ни назвала ключ.

    Имя ключа проверять бессмысленно: GigaChat переводит его вместе с
    текстом — в прогонах приходили и `технологии`, и ` кандидатов`
    с ведущим пробелом. Зато строение ответа стабильно: это список
    словарей с полями названия. По нему и ищем, вглубь на один уровень.
    """
    if _похоже_на_кандидатов(ответ):
        return ответ, ""
    if not isinstance(ответ, dict):
        return [], ""
    for ключ, значение in ответ.items():
        if _похоже_на_кандидатов(значение):
            return значение, str(ключ)
    for значение in ответ.values():
        вложенный, ключ = _найти_список(значение)
        if вложенный:
            return вложенный, ключ
    return [], ""


def _зонтичное(name: str, query: str) -> bool:
    """Название целиком состоит из слов области и слов запроса.

    «Artificial Intelligence in Cybersecurity» по запросу про
    кибербезопасность — это пересказ запроса, а не найденная технология.
    Модель просят так не делать, но она делает, поэтому проверяем сами.
    """
    from src.collect.vocab import GENERIC

    слова_запроса = {w.lower() for w in re.findall(r"[\w\-]+", query or "")}
    свои = [
        w.lower()
        for w in re.findall(r"[^\W\d_][\w\-]+", name or "", re.UNICODE)
        if len(w) > 2
    ]
    значимые = [
        w for w in свои
        if w not in GENERIC and w not in SKIP and w not in слова_запроса
    ]
    return not значимые


def match_documents(
    name: str,
    documents: list[dict[str, Any]],
    min_share: float = MIN_TOKEN_SHARE,
) -> list[dict[str, Any]]:
    """Документы, в которых технология действительно упоминается.

    Зачем это нужно, хотя модель и сама присылает номера. Модель называет
    технологию по одному заголовку и в `docs` ставит один номер — в живом
    прогоне так и вышло: десять кандидатов, у каждого по одной работе, порог
    в два документа отсеял всё. Но связь «технология — документ» не обязана
    приходить от модели: её можно установить самим, поиском слов названия по
    заголовкам и аннотациям, причём по всем собранным документам, а не только
    по тем шестидесяти, что уходили в запрос.

    Так распределение обязанностей становится честным: модель даёт название,
    подтверждение даёт поиск по текстам.
    """
    слова = [w.lower() for w in _TOKEN.findall(name or "")]
    значимые = [w for w in слова if w not in SKIP and len(w) > 2]
    if not значимые:
        return []

    нужно = max(1, math.ceil(len(значимые) * min_share))
    найдены = []
    for doc in documents:
        текст = f"{doc.get('title') or ''} {doc.get('abstract') or ''}".lower()
        if sum(1 for w in значимые if w in текст) >= нужно:
            найдены.append(doc)
    return найдены


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

    показанные = _sample(documents)

    сырой: list[str] = []
    ответ, модель = ask_json(
        provider,
        SYSTEM,
        PROMPT.format(
            query=query,
            titles=_format_titles(показанные),
            limit=MAX_CANDIDATES,
        ),
        raw_out=сырой,
    )

    сырые, ключ = _найти_список(ответ)
    if ключ not in ("candidates", ""):
        # GigaChat переводит и сам ключ: приходило и "технологии",
        # и " кандидатов" с пробелом в начале. Поэтому список ищется
        # по строению ответа, а не по имени ключа.
        log.info("Модель назвала список %r вместо candidates", ключ)

    if not сырые:
        # Без сырого ответа непонятно, кто виноват: ответ оборвался, модель
        # отказалась или вернула структуру не того вида. Печатаем начало.
        log.warning(
            "Модель не вернула кандидатов, откатываемся на частотный способ. "
            "Ключи ответа: %s. Начало ответа: %.300s",
            list(ответ)[:6] or "нет",
            (сырой[-1] if сырой else "ответа не было"),
        )
        return []

    кандидаты: list[dict[str, Any]] = []
    видели: set[str] = set()
    без_подтверждения = 0
    зонтичных = 0

    for item in сырые:
        name_ru = str(item.get("name_ru") or "").strip()
        name_en = str(item.get("name_en") or "").strip()
        if not name_ru and not name_en:
            continue

        ключ = (name_ru or name_en).lower()
        if ключ in видели:
            continue

        if _зонтичное(name_ru, query) and _зонтичное(name_en, query):
            зонтичных += 1
            log.debug("Кандидат %r — название области, отброшен", name_ru or name_en)
            continue

        # Номера от модели — только одна из двух опор. Вторая, основная:
        # поиск слов названия по всем собранным документам.
        связанные: list[dict[str, Any]] = []
        адреса: set[str] = set()
        for номер in item.get("docs") or []:
            try:
                индекс = int(номер) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= индекс < len(показанные):
                doc = показанные[индекс]
                if doc.get("url") not in адреса:
                    адреса.add(doc.get("url"))
                    связанные.append(doc)

        for doc in match_documents(name_en or name_ru, documents):
            if doc.get("url") not in адреса:
                адреса.add(doc.get("url"))
                связанные.append(doc)

        # Кандидат без подтверждённых документов — это ровно то, что ТЗ
        # запрещает: выдача на знаниях модели, а не на найденных публикациях.
        if len(связанные) < MIN_DOCS_PER_CANDIDATE:
            без_подтверждения += 1
            log.debug("Кандидат %r подтверждён %s документами, отброшен",
                      name_en or name_ru, len(связанные))
            continue

        видели.add(ключ)
        кандидаты.append({
            "name_ru": name_ru or name_en,
            "name_en": name_en or name_ru,
            "docs": связанные,
            "model": модель,
        })

    кандидаты = _drop_subsumed(кандидаты)

    log.info(
        "Модель %s выделила кандидатов: %s из %s предложенных "
        "(без подтверждения документами: %s, названий области: %s)",
        модель, len(кандидаты), len(сырые), без_подтверждения, зонтичных,
    )
    return кандидаты


def _drop_subsumed(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Убирает кандидатов, целиком вложенных в другого.

    Модель называет и «совместная разработка компилятора и аппаратуры», и
    «архитектуры ускорителей и совместная разработка компилятора и
    аппаратуры» — по одним и тем же работам. Оставляем того, у кого больше
    подтверждающих документов.
    """
    порядок = sorted(candidates, key=lambda c: len(c["docs"]), reverse=True)
    итог: list[dict[str, Any]] = []

    for кандидат in порядок:
        слова = {w.lower() for w in _TOKEN.findall(кандидат["name_en"])} - SKIP
        адреса = {d.get("url") for d in кандидат["docs"]}
        вложен = False
        for принятый in итог:
            слова_п = {w.lower() for w in _TOKEN.findall(принятый["name_en"])} - SKIP
            адреса_п = {d.get("url") for d in принятый["docs"]}
            if слова and слова <= слова_п and адреса <= адреса_п:
                вложен = True
                break
        if not вложен:
            итог.append(кандидат)

    return итог


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
