"""Превращение пользовательского запроса в поисковые строки для источников.

Зачем. Жюри вводит запрос по-русски: «слабые сигналы в кибербезопасности».
OpenAlex и arXiv индексируют англоязычные тексты, и по русской строке
возвращают случайный мусор — в первом живом прогоне пришли работы про
пространства Морри и углеродные нанотрубки, то есть не по теме вообще.

Поэтому перед сбором русский запрос превращается в английские поисковые
строки. Если языковая модель настроена — спрашиваем её. Если нет —
работает словарь по шести областям кейса плюс срезание служебных слов.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")

# Слова-обёртки: они описывают задачу, а не предмет поиска.
FRAMING = (
    # Сначала длинные фразы, потом короткие: иначе «технологии в» срежется
    # раньше и от «зарождающиеся технологии в» останется «зарождающиеся».
    "зарождающиеся технологии", "зарождающихся технологий",
    "перспективные технологии", "перспективных технологий",
    "новые технологии", "новых технологий", "прорывные технологии",
    "слабые сигналы", "слабых сигналов", "слабый сигнал",
    "зарождающиеся тренды", "зарождающихся трендов",
    "перспективные решения", "перспективных решений",
    "технологии в", "технологий в", "тренды в", "трендов в",
    "новое в", "что нового в", "в области", "в сфере", "в отрасли",
)

# Шесть областей кейса плюс частые синонимы. Значение — поисковые строки.
AREA_TERMS: dict[str, list[str]] = {
    "кибербезопасн": ["cybersecurity emerging technology", "security of AI systems"],
    "безопасност": ["cybersecurity emerging technology", "AI security"],
    "защит": ["AI security", "adversarial robustness"],
    "финтех": ["fintech emerging technology", "financial technology innovation"],
    "финанс": ["financial technology innovation", "payments infrastructure"],
    "банк": ["banking technology innovation", "financial technology"],
    "робот": ["robotics emerging technology", "autonomous robots"],
    "промышленн": ["industrial AI", "manufacturing artificial intelligence"],
    "производств": ["industrial AI", "smart manufacturing"],
    "инфраструктур": ["AI infrastructure", "machine learning systems infrastructure"],
    "вычислен": ["computing infrastructure", "accelerated computing"],
    "edge": ["edge computing inference", "on-device machine learning"],
    "периферийн": ["edge computing inference", "on-device machine learning"],
    "интернет вещей": ["internet of things edge", "IoT devices"],
    "искусственн": ["artificial intelligence emerging methods"],
    "ии": ["artificial intelligence emerging methods"],
    "медицин": ["medical technology innovation", "healthcare AI"],
    "биотех": ["biotechnology emerging", "synthetic biology"],
    "энерг": ["energy technology innovation", "energy storage"],
    "материал": ["advanced materials", "materials science innovation"],
    "квантов": ["quantum technology", "quantum computing hardware"],
    "космос": ["space technology innovation", "satellite systems"],
    "транспорт": ["transportation technology", "autonomous vehicles"],
    "сельск": ["agricultural technology", "precision agriculture"],
    "образован": ["education technology", "learning technology"],
}

SYSTEM = (
    "Ты помогаешь искать научные публикации. Переводишь запрос пользователя "
    "в короткие английские поисковые строки. Отвечаешь только объектом JSON."
)

# Раньше модели уходил запрос целиком, и GigaChat переводил «слабые сигналы
# в кибербезопасности» как «cybersecurity weak signals detection» и «early
# warning cyber threats» — хотя промпт это запрещал. Поиск находил статьи
# про обнаружение угроз, а не про новые технологии в кибербезопасности.
# Теперь модель видит только тему, а обёртку «слабые сигналы» мы срезаем сами.
PROMPT = """Область: «{topic}»

Нужно найти в научных базах свежие работы о новых технических решениях в
этой области. Предложи {count} английских поисковых строк, каждая — про
отдельное техническое направление внутри области, где сейчас появляются
новые методы, протоколы, устройства или архитектуры.

Верни JSON:
{{"queries": ["строка 1", "строка 2", "строка 3", "строка 4", "строка 5"]}}

Правила:
- строки короткие, 2–5 слов, как ищут в научной базе;
- каждая строка — конкретное направление, а не вся область целиком:
  для кибербезопасности подходит «post-quantum cryptography migration»,
  а «cybersecurity threats» не подходит;
- не используй слова weak signal, early warning, emerging, trend, subtle,
  detection of risks — это описание задачи, а не предмета поиска."""

QUERY_COUNT = 5

# Страховка на случай, если модель всё же вставит слова задачи.
ЗАПРЕТНЫЕ_СЛОВА = ("weak signal", "early warning", "emerging trend", "subtle", "trend")


def is_russian(text: str) -> bool:
    """Есть ли в запросе кириллица."""
    return bool(CYRILLIC.search(text or ""))


def strip_framing(query: str) -> str:
    """Убирает «слабые сигналы в ...» и оставляет саму тему."""
    lowered = (query or "").lower()
    for phrase in FRAMING:
        lowered = lowered.replace(phrase, " ")
    тема = re.sub(r"\s+", " ", lowered).strip(" ,.:;-")
    # Висящий предлог после срезания: «в кибербезопасности» -> «кибербезопасности».
    return re.sub(r"^(в|во|для|по|о|об)\s+", "", тема)


def from_dictionary(query: str) -> list[str]:
    """Поисковые строки по словарю областей. Запасной вариант без модели."""
    тема = strip_framing(query)
    найдено: list[str] = []
    for ключ, строки in AREA_TERMS.items():
        # Короткие ключи ищем только как отдельные слова, иначе «ии»
        # находится внутри «виноделии» и тема подменяется.
        if len(ключ) <= 3:
            совпало = re.search(rf"(?<!\w){re.escape(ключ)}(?!\w)", тема) is not None
        else:
            совпало = ключ in тема
        if совпало:
            for строка in строки:
                if строка not in найдено:
                    найдено.append(строка)
    return найдено


def from_model(query: str, provider: Any) -> list[str]:
    """Поисковые строки от языковой модели."""
    from src.texts.providers import ask_json

    тема = strip_framing(query) or query
    ответ, модель = ask_json(
        provider, SYSTEM, PROMPT.format(topic=тема, count=QUERY_COUNT)
    )
    # GigaChat переводит и ключи JSON, поэтому берём первый список строк.
    сырые = ответ.get("queries")
    if not isinstance(сырые, list):
        сырые = next((v for v in ответ.values() if isinstance(v, list)), [])
    строки = [
        str(s).strip() for s in сырые
        if str(s).strip() and not any(w in str(s).lower() for w in ЗАПРЕТНЫЕ_СЛОВА)
    ]
    if строки:
        log.info("Запрос переведён моделью %s (тема %r): %s", модель, тема, строки)
    return строки[:QUERY_COUNT]


def search_queries(query: str, provider: Any | None = None) -> list[str]:
    """Что именно отправлять в OpenAlex и arXiv.

    Латинский запрос уходит как есть. Русский — переводится: сначала
    моделью, если она настроена, иначе по словарю. Если не вышло ни то
    ни другое, возвращаем исходную строку и пишем предупреждение: выдача
    будет плохой, и это должно быть видно в логах, а не молча.
    """
    query = (query or "").strip()
    if not query:
        return []

    if not is_russian(query):
        return [query]

    if provider is None:
        from src.texts.providers import get_provider

        provider = get_provider()

    if provider is not None:
        строки = from_model(query, provider)
        if строки:
            return строки

    строки = from_dictionary(query)
    if строки:
        log.info("Запрос переведён по словарю: %s", строки)
        return строки

    log.warning(
        "Русский запрос %r не удалось перевести: нет языковой модели и нет "
        "совпадений в словаре. Источники вернут нерелевантные документы.",
        query,
    )
    return [query]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    примеры = [
        "слабые сигналы в кибербезопасности",
        "перспективные решения в финтехе",
        "технологии в робототехнике",
        "quantum sensing",
        "что нового в периферийных вычислениях",
        "слабые сигналы в виноделии",
    ]
    for пример in примеры:
        print(f"{пример!r} -> {search_queries(пример, provider=None)}")
