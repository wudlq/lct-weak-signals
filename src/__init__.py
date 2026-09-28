"""Пакет системы поиска слабых сигналов.

При импорте подхватываем .env из корня проекта, чтобы ключи работали при
любом способе запуска: python -m src.pipeline, scripts/*.py, streamlit.
Переменные, уже заданные в окружении (Docker, секреты Streamlit Cloud),
не перезаписываются.
"""

import pathlib

try:
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:  # без python-dotenv просто берём переменные окружения
    pass
