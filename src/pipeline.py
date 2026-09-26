"""Сквозной пайплайн: запрос на входе, карточки кандидатов на выходе.

Порядок работы:
    запрос -> сборщики -> нормализация и склейка дублей -> база
           -> выделение кандидатов -> признаки -> модель -> карточки

Кандидатов выделяем по повторяющимся ключевым фразам из названий и
аннотаций. Это осознанно простой способ вместо собственной кластеризации:
он работает за секунды, его легко объяснить жюри и он не ломается на
маленькой выборке документов.

Запуск:
    python -m src.pipeline "слабые сигналы в кибербезопасности"
"""

from __future__ import annotations

import collections
import json
import logging
import pathlib
import re
from typing import Any, Callable

from src.collect import arxiv, openalex
from src.collect.normalize import prepare
from src.collect.query import search_queries
from src.features.build import profile_from_docs
from src.model.predict import load_model, reject_reason, score
from src.storage import db

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache"

TOP_N = 15
MIN_DOCS_PER_CANDIDATE = 2   # фраза из одного документа — это не тренд
MAX_DOC_SHARE = 0.4          # фраза почти в каждом документе — это сам запрос
NGRAM_SIZES = (2, 3)
MAX_CANDIDATES = 60

# Слова, которые сами по себе ничего не значат и портят названия кандидатов.
STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "using", "based",
    "via", "into", "over", "new", "novel", "toward", "towards", "approach",
    "method", "methods", "model", "models", "system", "systems", "study",
    "analysis", "paper", "results", "propose", "proposed", "we", "our",
    "a", "an", "of", "in", "on", "to", "by", "is", "are", "be", "can",
    # Слова про стадию и оформление работы. В признаках они важны, а в
    # названии кандидата дают мусор вроде «proof concept implementation».
    "present", "presents", "prototype", "pilot", "proof", "concept",
    "implementation", "preliminary", "experimental", "feasibility",
    "deployment", "demonstrated", "evaluation", "framework", "case",
    "early", "stage", "first", "initial", "towards", "part",
}

# Академические обороты. В живом прогоне из-за них в ТОП-15 попали
# «consistently outperforms», «has been observed» и «root mean square» —
# это язык статьи, а не название технологии.
BOILERPLATE = {
    "outperforms", "state", "art", "baseline", "baselines", "benchmark",
    "benchmarks", "dataset", "datasets", "accuracy", "performance",
    "experiments", "experiment", "observed", "consistently", "significantly",
    "compared", "comparison", "improvement", "improvements", "error",
    "errors", "mean", "square", "root", "average", "values", "value",
    "international", "scientific", "conference", "journal", "review",
    "survey", "overview", "introduction", "conclusion", "discussion",
    "recent", "advances", "future", "challenges", "opportunities",
    "problem", "problems", "solution", "solutions", "application",
    "applications", "research", "work", "works", "data",
}

_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ][\w\-]+", re.UNICODE)


def _cache_file(query: str) -> pathlib.Path:
    """Имя файла кеша для запроса — безопасное для файловой системы."""
    slug = re.sub(r"[^\w]+", "-", query.lower(), flags=re.UNICODE).strip("-")[:80]
    return CACHE_DIR / f"{slug or 'query'}.json"


def load_cache(query: str) -> list[dict[str, Any]] | None:
    """Прогретые направления лежат в репозитории — демо работает без сети."""
    file = _cache_file(query)
    if not file.exists():
        return None
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("Кеш %s повреждён, игнорируем", file.name)
        return None


def save_cache(query: str, candidates: list[dict[str, Any]]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_file(query).write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def collect(query: str, limit_per_source: int = 100) -> list[dict[str, Any]]:
    """Собирает документы из всех источников. Падение одного не ломает остальные.

    Русский запрос сначала превращается в английские поисковые строки:
    OpenAlex и arXiv индексируют англоязычные тексты и по кириллице
    возвращают документы не по теме.
    """
    строки = search_queries(query)
    log.info("Поисковые строки: %s", строки)

    documents: list[dict[str, Any]] = []
    источники: list[tuple[str, Callable[..., list[dict[str, Any]]]]] = [
        ("OpenAlex", openalex.search),
        ("arXiv", arxiv.search),
    ]
    на_строку = max(limit_per_source // max(len(строки), 1), 20)

    for строка in строки:
        for name, search_fn in источники:
            try:
                batch = search_fn(строка, limit=на_строку)
                log.info("%s по %r: %s документов", name, строка, len(batch))
                documents.extend(batch)
            except Exception as error:  # источник не должен ронять пайплайн
                log.warning("%s недоступен: %s", name, error)
    return prepare(documents)


def _phrases(text: str) -> set[str]:
    """Осмысленные словосочетания из текста.

    Фраза принимается, только если в ней есть хотя бы одно содержательное
    слово: иначе в кандидаты лезут обороты вроде «consistently outperforms».
    """
    words = [w.lower() for w in _WORD.findall(text or "")]
    words = [w for w in words if w not in STOPWORDS and len(w) > 2]
    found: set[str] = set()
    for size in NGRAM_SIZES:
        for i in range(len(words) - size + 1):
            кусок = words[i : i + size]
            if all(w in BOILERPLATE for w in кусок):
                continue
            if кусок[0] in BOILERPLATE or кусок[-1] in BOILERPLATE:
                continue
            found.add(" ".join(кусок))
    return found


def extract_candidates(documents: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Группирует документы по повторяющимся фразам.

    Возвращает словарь «фраза -> документы, где она встречается».
    """
    if not documents:
        return {}

    # Названия технологий живут в заголовках. Аннотации дают язык статьи —
    # в первом живом прогоне именно из них полезли обрывки вроде
    # «has been observed». Поэтому кандидатов берём только из заголовков,
    # а аннотации остаются для признаков.
    по_документам: list[set[str]] = []
    счётчик: collections.Counter[str] = collections.Counter()
    for doc in documents:
        фразы = _phrases(doc.get("title") or "")
        по_документам.append(фразы)
        счётчик.update(фразы)

    предел = max(int(len(documents) * MAX_DOC_SHARE), MIN_DOCS_PER_CANDIDATE + 1)
    отобранные = [
        фраза for фраза, количество in счётчик.most_common()
        if MIN_DOCS_PER_CANDIDATE <= количество <= предел
    ]

    группы_всех: dict[str, list[dict[str, Any]]] = {
        фраза: [doc for doc, фразы in zip(documents, по_документам) if фраза in фразы]
        for фраза in отобранные
    }

    # Убираем обрывки: «quantum key» внутри «post quantum key» — это одно и то же.
    # Длинная фраза читается как название технологии, короткая — как мусор.
    группы: dict[str, list[dict[str, Any]]] = {}
    for фраза in sorted(группы_всех, key=lambda p: (-len(p.split()), -len(p))):
        документы_фразы = {d["source_id"] for d in группы_всех[фраза]}
        поглощена = False
        for принятая in группы:
            if фраза in принятая or принятая in фраза:
                документы_принятой = {d["source_id"] for d in группы[принятая]}
                пересечение = документы_фразы & документы_принятой
                if пересечение and len(пересечение) / len(документы_фразы) >= 0.8:
                    поглощена = True
                    break
        if not поглощена:
            группы[фраза] = группы_всех[фраза]
        if len(группы) >= MAX_CANDIDATES:
            break
    return группы


def _card(
    technology: str,
    docs: list[dict[str, Any]],
    model: Any,
    docs_collected: int = 0,
) -> dict[str, Any]:
    """Карточка кандидата в формате, о котором договорились с интерфейсом.

    Про названия. Фразы вытаскиваются из заголовков и аннотаций, а они
    английские. ТЗ требует всю аналитическую выдачу на русском, поэтому:
      technology          — русское название, его проставляет модуль текстов;
      technology_original — исходная английская фраза, остаётся рядом.
    Пока модуль текстов не отработал, в technology лежит оригинал, а
    technology_language говорит интерфейсу, что перевода ещё нет.
    """
    profile = profile_from_docs(technology, docs)
    оценка = score(profile, model=model)
    причина = reject_reason(оценка["features"], оценка["score"])

    return {
        "technology": technology,
        "technology_original": technology,
        "technology_language": "en",
        "area": "",  # область проставляется по запросу, если он её называет
        "score": оценка["score"],
        "top_features": [
            {
                "name": item["name"],
                "value": item["value"],
                "direction": item["direction"],
            }
            for item in оценка["top_features"]
        ],
        "description": None,   # заполняет модуль текстов
        "advantage": None,
        "case_example": None,
        "sources": docs[:5],   # в карточку кладём до пяти подтверждений
        "verdict": "сигнал" if причина is None else "отклонено",
        "reject_reason": причина,
        "doc_count": len(docs),          # документов под этим кандидатом
        "sources_shown": min(len(docs), 5),
        # Сколько документов собрано по запросу целиком. Значение одинаковое
        # во всех карточках: это факт про запрос, а не про кандидата. Держим
        # его здесь, чтобы run() остался возвращать список, как договорились.
        "docs_collected": docs_collected,
    }


def run(
    query: str,
    use_cache: bool = True,
    limit_per_source: int = 100,
    save_to_db: bool = True,
    with_texts: bool = True,
) -> list[dict[str, Any]]:
    """Главная функция. Интерфейс вызывает только её.

    Возвращает список карточек: сначала сигналы по убыванию уверенности,
    затем отклонённые кандидаты с причиной.
    """
    if use_cache:
        кеш = load_cache(query)
        if кеш:
            log.info("Ответ из кеша: %s карточек", len(кеш))
            return кеш

    документы = collect(query, limit_per_source=limit_per_source)
    if not документы:
        log.warning("По запросу %r ничего не собрано", query)
        return []

    if save_to_db:
        db.save_docs(документы, query=query)

    группы = extract_candidates(документы)
    log.info("Кандидатов до отбора: %s", len(группы))

    model = load_model()
    карточки = [
        _card(фраза, docs, model, docs_collected=len(документы))
        for фраза, docs in группы.items()
    ]

    сигналы = sorted(
        (c for c in карточки if c["verdict"] == "сигнал"),
        key=lambda c: c["score"], reverse=True,
    )[:TOP_N]
    отклонённые = sorted(
        (c for c in карточки if c["verdict"] == "отклонено"),
        key=lambda c: c["score"], reverse=True,
    )

    результат = сигналы + отклонённые

    # Русские названия, описания и кейсы — только для ТОП-15: на отклонённых
    # они не нужны, а обращения к языковой модели стоят лимитов.
    if with_texts and сигналы:
        from src.texts.generate import describe_all

        describe_all(сигналы)

    if save_to_db:
        db.save_candidates(результат, query=query)
    save_cache(query, результат)
    return результат


def stats(candidates: list[dict[str, Any]]) -> dict[str, int]:
    """Три счётчика для дашборда — прямое требование ТЗ.

    «Обработано источников» — это все документы, собранные по запросу,
    а не те пять, что показаны в карточке. Считать по карточкам нельзя:
    число вышло бы заниженным в разы.
    """
    if not candidates:
        return {"кандидатов": 0, "обработано_источников": 0, "уверенность_выше_75": 0}

    показано = {
        doc.get("source_id")
        for card in candidates
        for doc in card.get("sources", [])
        if doc.get("source_id")
    }
    обработано = max(
        (card.get("docs_collected") or 0 for card in candidates), default=0
    )

    return {
        "кандидатов": len(candidates),
        "обработано_источников": обработано or len(показано),
        "показано_источников": len(показано),
        "уверенность_выше_75": sum(
            1 for c in candidates if c["verdict"] == "сигнал" and c["score"] > 0.75
        ),
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    запрос = sys.argv[1] if len(sys.argv) > 1 else "слабые сигналы в кибербезопасности"
    карточки = run(запрос)
    print(json.dumps(stats(карточки), ensure_ascii=False, indent=2))
    for card in карточки[:TOP_N]:
        предикторы = ", ".join(
            f"{p['direction']}{p['name']}" for p in card["top_features"]
        )
        print(f"{card['score']:.2f}  {card['technology']}  [{предикторы}]")
