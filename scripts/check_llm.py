"""Диагностика: что языковая модель на самом деле отвечает на наш запрос.

Нужен, когда в логе прогона видно «Модель не вернула кандидатов»: сам прогон
проглатывает ответ и откатывается на частотный способ, а здесь ответ виден
целиком — сразу понятно, оборвался он, оказался не JSON или пришёл с другими
ключами.

Заголовки берутся из базы, то есть ровно те, на которых упало.

Запуск:
    python scripts/check_llm.py "слабые сигналы в кибербезопасности"
"""

from __future__ import annotations

import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.collect import candidates  # noqa: E402
from src.storage import db  # noqa: E402
from src.texts.providers import ask_json, get_provider  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    запрос = sys.argv[1] if len(sys.argv) > 1 else "слабые сигналы в кибербезопасности"

    поставщик = get_provider()
    if поставщик is None:
        print("LLM_PROVIDER не задан. Проверьте .env")
        return 1
    print(f"Поставщик: {поставщик.name}")

    # Только документы этого запроса: в базе лежат все прошлые прогоны, и без
    # фильтра модель получила бы заголовки из чужой темы.
    документы = db.load_docs(запрос) or db.load_docs()
    if not документы:
        print("В базе нет документов. Сначала прогоните пайплайн.")
        return 1
    print(f"Документов в базе: {len(документы)}, в запрос уйдёт "
          f"{min(len(документы), candidates.MAX_TITLES)}")

    сырой: list[str] = []
    ответ, модель = ask_json(
        поставщик,
        candidates.SYSTEM,
        candidates.PROMPT.format(
            query=запрос,
            titles=candidates._format_titles(candidates._sample(документы)),
            limit=candidates.MAX_CANDIDATES,
        ),
        raw_out=сырой,
    )

    print(f"\nМодель: {модель}")
    print("=" * 70)
    print(сырой[-1] if сырой else "ответа не было вообще (смотрите WARNING выше)")
    print("=" * 70)
    print(f"\nРазобранные ключи: {list(ответ) or 'нет'}")
    список = ответ.get("candidates") or ответ.get("технологии") or []
    print(f"Кандидатов в ответе: {len(список)}")
    for item in список[:5]:
        print("  ", item)

    итог = candidates.extract(документы, запрос, provider=поставщик)
    print(f"\nПосле отбора осталось: {len(итог)}")
    for c in итог[:10]:
        print(f"  {c['name_ru']} ({c['name_en']}) — документов: {len(c['docs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
