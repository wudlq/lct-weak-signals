"""Оценка кандидата и объяснение, почему модель решила именно так.

Интерфейс показывает «ключевые предикторы» — три признака с наибольшим
вкладом. Для линейной модели вклад считается честно: нормированное значение
признака, умноженное на коэффициент.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

import numpy as np
import pandas as pd

from src.features.build import FEATURE_LABELS, FEATURE_NAMES, Profile, features_of

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODEL_FILE = ROOT / "models" / "model.joblib"

_model_cache: Any = None


def load_model(path: pathlib.Path | None = None) -> Any:
    """Загружает обученную модель. Кешируется, чтобы не читать файл на каждый запрос."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    file = pathlib.Path(path or MODEL_FILE)
    if not file.exists():
        raise FileNotFoundError(
            f"Нет обученной модели {file}. Сначала запустите: python -m src.model.train"
        )
    import joblib

    _model_cache = joblib.load(file)
    return _model_cache


def contributions(model: Any, values: dict[str, float]) -> list[dict[str, Any]]:
    """Вклад каждого признака в решение, от большего к меньшему."""
    scaler = model.named_steps["scaler"]
    clf = model.named_steps["clf"]

    row = pd.DataFrame([[float(values[name]) for name in FEATURE_NAMES]], columns=FEATURE_NAMES)
    scaled = scaler.transform(row)[0]
    weights = clf.coef_[0]

    items = []
    for name, z, weight in zip(FEATURE_NAMES, scaled, weights):
        вклад = float(z * weight)
        подпись = FEATURE_LABELS[name]
        # «Только медиа» — признак-флаг. Когда он равен нулю, плюс к сигналу
        # даёт как раз наличие науки, а подпись «+только медиа, без науки»
        # читалась бы наоборот. Называем то, что есть на самом деле.
        if name == "media_only" and float(values[name]) == 0.0:
            подпись = "есть научные публикации"
        items.append({
            "name": подпись,
            "key": name,
            "value": round(float(values[name]), 3),
            "contribution": round(вклад, 3),
            "direction": "+" if вклад >= 0 else "-",
        })
    return sorted(items, key=lambda item: abs(item["contribution"]), reverse=True)


def score(profile: Profile, model: Any | None = None) -> dict[str, Any]:
    """Уверенность модели и объяснение для одного кандидата."""
    model = model or load_model()
    values = features_of(profile)

    frame = pd.DataFrame([values], columns=FEATURE_NAMES)
    probability = float(model.predict_proba(frame)[0][1])
    предикторы = contributions(model, values)

    return {
        "score": round(probability, 3),
        "features": values,
        "top_features": предикторы[:3],
        "all_features": предикторы,
    }


def reject_reason(values: dict[str, float], probability: float) -> str | None:
    """Почему кандидат не попал в сигналы — словами, а не числом.

    Порядок проверок важен: зрелость перекрывает всё остальное.
    """
    if probability >= 0.5:
        return None
    if values["stage_score"] >= 2.5 or values["maturity_words_ratio"] > 1.0:
        return "зрелая"
    if values["media_only"] == 1.0 or values["trusted_share"] == 0.0:
        return "хайп"
    return "шум"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    пример = Profile(
        technology="Пример технологии",
        area="Edge",
        texts=["early prototype of a new sensing method, pilot at two labs"],
        orgs=["MIT", "ETH"],
        urls=["https://arxiv.org/abs/2609.00001"],
        source_types=["препринт"],
    )
    результат = score(пример)
    print("скоринг:", результат["score"])
    for item in результат["top_features"]:
        print(f"  {item['direction']} {item['name']}: {item['value']} "
              f"(вклад {item['contribution']})")
