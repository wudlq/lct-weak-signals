"""Обучение модели и честный отчёт о метриках.

Модель намеренно простая — логистическая регрессия на восьми признаках.
Причина в ТЗ: система обязана показывать, по каким признакам наблюдение
отнесено к слабому сигналу. У линейной модели вклад признака — это просто
коэффициент, умноженный на нормированное значение, и его можно показать
пользователю. У трансформера такого объяснения нет.

Проверка идёт по областям, а не случайным разбиением: обучаемся на пяти
областях, проверяемся на шестой, и так шесть раз. Случайное разбиение
показало бы красивую цифру за счёт того, что модель выучила тему, а не
стадию технологии.

Запуск:
    python -m src.model.train
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.features.build import FEATURE_LABELS, FEATURE_NAMES, build_features, profile_from_row

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"

POSITIVES = DATA / "positives.csv"
NEGATIVES = DATA / "negatives.csv"
MODEL_FILE = MODELS / "model.joblib"
METRICS_FILE = REPORTS / "metrics.md"


def load_dataset(
    positives: pathlib.Path = POSITIVES,
    negatives: pathlib.Path = NEGATIVES,
) -> pd.DataFrame:
    """Собирает обучающую таблицу из двух файлов."""
    parts = []
    for path, label in ((positives, 1), (negatives, 0)):
        if not path.exists():
            raise FileNotFoundError(f"Нет файла {path}")
        frame = pd.read_csv(path)
        if frame.empty:
            log.warning("Файл %s пустой", path.name)
            continue
        frame["label"] = label
        parts.append(frame)

    if not parts:
        raise ValueError("Нет данных для обучения")

    data = pd.concat(parts, ignore_index=True)
    data["neg_type"] = data.get("neg_type", "").fillna("")
    return data


def make_features(data: pd.DataFrame, use_annotation: bool = True) -> pd.DataFrame:
    """Таблица данных -> таблица признаков, с сохранением меток.

    use_annotation=False — контрольный вариант: стадия и динамика считаются
    по описанию, а колонки stage и trend из разметки не используются.
    """
    профили = [profile_from_row(row) for row in data.to_dict("records")]
    if not use_annotation:
        for профиль in профили:
            профиль.stage_hint = ""
            профиль.trend_hint = ""
    features = build_features(профили)
    features["label"] = data["label"].to_numpy()
    features["neg_type"] = data["neg_type"].to_numpy()
    return features


def build_model() -> Pipeline:
    """Нормализация плюс логистическая регрессия."""
    return Pipeline([
        ("scaler", StandardScaler()),
        # C=0.1 — сильнее регуляризация, чем по умолчанию. На проверке по
        # областям F1 тот же, а уверенность перестаёт упираться в 1.00:
        # без этого почти любой свежий кандидат получал 99–100%, и шкала
        # в интерфейсе ничего не различала.
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", C=0.1)),
    ])


def cross_validate_by_area(features: pd.DataFrame) -> dict[str, Any]:
    """Проверка «обучились на пяти областях, проверились на шестой»."""
    области = sorted(a for a in features["area"].dropna().unique() if a)
    складки: list[dict[str, Any]] = []
    предсказания = np.full(len(features), np.nan)

    for область in области:
        тест = features["area"] == область
        обучение = ~тест
        if тест.sum() == 0 or features.loc[обучение, "label"].nunique() < 2:
            continue

        model = build_model()
        model.fit(features.loc[обучение, FEATURE_NAMES], features.loc[обучение, "label"])
        preds = model.predict(features.loc[тест, FEATURE_NAMES])
        предсказания[тест.to_numpy()] = preds

        метки = features.loc[тест, "label"]
        if метки.nunique() < 2:
            # В области только негативы (например, «Кибербезопасность»):
            # precision и recall тут не определены, считаем долю отсеянных.
            складки.append({
                "область": область,
                "объектов": int(тест.sum()),
                "только_негативы": True,
                "отсеяно": int((preds == 0).sum()),
            })
            continue

        p, r, f1, _ = precision_recall_fscore_support(
            метки, preds, average="binary", zero_division=0
        )
        складки.append({
            "область": область,
            "объектов": int(тест.sum()),
            "precision": round(float(p), 3),
            "recall": round(float(r), 3),
            "f1": round(float(f1), 3),
        })

    заполнено = ~np.isnan(предсказания)
    p, r, f1, _ = precision_recall_fscore_support(
        features.loc[заполнено, "label"], предсказания[заполнено],
        average="binary", zero_division=0,
    )

    # Отдельно смотрим, как ловятся три типа негатива — это прямой пункт ТЗ.
    по_типам = []
    for тип in ("зрелая", "хайп", "шум"):
        маска = (features["neg_type"] == тип) & заполнено
        if маска.sum() == 0:
            continue
        отсеяно = int((предсказания[маска.to_numpy()] == 0).sum())
        по_типам.append({
            "тип": тип,
            "всего": int(маска.sum()),
            "отсеяно_верно": отсеяно,
            "доля": round(отсеяно / int(маска.sum()), 3),
        })

    return {
        "общее": {
            "precision": round(float(p), 3),
            "recall": round(float(r), 3),
            "f1": round(float(f1), 3),
            "объектов": int(заполнено.sum()),
        },
        "по_областям": складки,
        "по_типам_негатива": по_типам,
    }


def feature_weights(model: Pipeline) -> list[tuple[str, float]]:
    """Коэффициенты обученной модели — это и есть её методология в числах."""
    coefficients = model.named_steps["clf"].coef_[0]
    pairs = list(zip(FEATURE_NAMES, (float(c) for c in coefficients)))
    return sorted(pairs, key=lambda pair: abs(pair[1]), reverse=True)


def write_report(metrics: dict[str, Any], model: Pipeline, data: pd.DataFrame) -> None:
    """Отчёт для жюри: цифры и честное описание того, как они получены."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    общее = metrics["общее"]

    негативов = int((data["label"] == 0).sum())
    черновые = data.loc[data["label"] == 0, "tech_id"].astype(str).str.startswith("neg-fix")
    на_черновиках = bool(черновые.any())

    lines = [
        "# Отчёт о качестве модели",
        "",
        f"Обучающая выборка: {int((data['label'] == 1).sum())} слабых сигналов "
        f"и {негативов} примеров того, что сигналом не является.",
        "",
    ]

    if на_черновиках:
        lines += [
            "> **Эти числа нельзя показывать жюри.** Модель обучена на черновых",
            "> негативах из `tests/fixtures/`, написанных наспех для проверки кода.",
            "> Они отличаются от положительных примеров стилем текста, поэтому",
            "> модель разделяет два стиля письма, а не раннюю и зрелую технологию.",
            "> После ручной разметки нужно перезапустить обучение — цифра станет",
            "> ниже, и это будет честная цифра.",
            "",
        ]

    lines += [
        "## Метрики",
        "",
        "| Метрика | Значение |",
        "| --- | --- |",
        f"| Precision | {общее['precision']} |",
        f"| Recall | {общее['recall']} |",
        f"| F1 | {общее['f1']} |",
        f"| Объектов в проверке | {общее['объектов']} |",
        "",
        "## Как получены эти числа",
        "",
        "Проверка идёт по областям, а не случайным разбиением. Одна область",
        "откладывается, модель учится на остальных и проверяется на отложенной,",
        "и так по очереди для каждой. Каждый объект оценён моделью, которая его",
        "тему при обучении не видела.",
        "",
        "| Область в проверке | Объектов | Precision | Recall | F1 |",
        "| --- | --- | --- | --- | --- |",
    ]
    только_негативы = []
    for fold in metrics["по_областям"]:
        if fold.get("только_негативы"):
            только_негативы.append(fold)
            continue
        lines.append(
            f"| {fold['область']} | {fold['объектов']} | {fold['precision']} "
            f"| {fold['recall']} | {fold['f1']} |"
        )
    if только_негативы:
        lines += [
            "",
            "Часть негативов взята из соседних областей, где положительных",
            "примеров нет. Там считаем только, сколько модель отсеяла:",
            "",
            "| Область | Негативов | Отсеяно |",
            "| --- | --- | --- |",
        ]
        for fold in только_негативы:
            lines.append(f"| {fold['область']} | {fold['объектов']} | {fold['отсеяно']} |")

    if metrics["по_типам_негатива"]:
        lines += [
            "",
            "## Отсев по типам",
            "",
            "ТЗ отдельным пунктом оценивает отделение зрелых технологий,",
            "маркетингового хайпа и информационного шума, поэтому смотрим их порознь.",
            "",
            "| Тип | Всего | Отсеяно верно | Доля |",
            "| --- | --- | --- | --- |",
        ]
        for item in metrics["по_типам_негатива"]:
            lines.append(
                f"| {item['тип']} | {item['всего']} | {item['отсеяно_верно']} | {item['доля']} |"
            )

    if metrics.get("без_разметки"):
        б = metrics["без_разметки"]
        lines += [
            "",
            "## Проверка на утечку из разметки",
            "",
            "Признаки «стадия развития» и «динамика упоминаний» на обучении берутся",
            "из колонок stage и trend, которые заполнил разметчик. У негативов там",
            "написано «зрелая» и «стабильная», у позитивов — «Пилот» и «растёт",
            "быстро», так что часть качества может идти от самой разметки. Поэтому",
            "повторяем ту же проверку, но стадию и динамику считаем только по",
            "описанию технологии, без этих колонок. Это нижняя оценка — ближе к",
            "тому, что видит модель на живом запросе, где колонок нет.",
            "",
            "| Вариант | Precision | Recall | F1 |",
            "| --- | --- | --- | --- |",
            f"| С колонками stage и trend | {общее['precision']} | {общее['recall']} | {общее['f1']} |",
            f"| Без них, только описание | {б['precision']} | {б['recall']} | {б['f1']} |",
        ]

    lines += [
        "",
        "## Вклад признаков",
        "",
        "Положительный коэффициент толкает кандидата к слабому сигналу,",
        "отрицательный — от него.",
        "",
        "| Признак | Коэффициент |",
        "| --- | --- |",
    ]
    for name, weight in feature_weights(model):
        lines.append(f"| {FEATURE_LABELS[name]} | {weight:+.3f} |")

    lines += [
        "",
        "## Ограничения, о которых мы знаем",
        "",
        "- Примеры-негативы собраны и размечены командой вручную, а не взяты",
        "  из закрытого датасета организаторов. На их выборке числа будут другими.",
        "- Положительные примеры пришли из одного источника разметки, поэтому",
        "  у них общий стиль описания. Негативы размечены в том же формате, но",
        "  описания у них в среднем длиннее (около 235 знаков против 190), и",
        "  колонки стадии и тренда заполнены другим словарём. Чтобы модель не",
        "  выучила словарь разметчика, слова ранней стадии и зрелости считаются",
        "  только по названию и описанию, а не по этим колонкам.",
        "- Веса около нуля у «слов ранней стадии» и «доли доверенных источников»",
        "  значат, что в обучающих строках по ним почти нечего различать: описания",
        "  короткие и русские, слов prototype или pilot в них единицы, а ссылок",
        "  на научные домены мало у обоих классов. На живом запросе эти признаки",
        "  считаются по английским аннотациям статей, где такие слова встречаются.",
        "- Признаки «стадия» и «динамика» на обучении считаются по тексту, а на",
        "  живом запросе — по датам публикаций. Шкала одна, способ измерения разный.",
        "",
    ]
    METRICS_FILE.write_text("\n".join(lines), encoding="utf-8")
    log.info("Отчёт записан: %s", METRICS_FILE)


def main() -> dict[str, Any]:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = load_dataset()
    features = make_features(data)

    if features["label"].nunique() < 2:
        raise SystemExit(
            "В выборке только один класс. Нужен файл data/negatives.csv "
            "с размеченными примерами — без него обучать нечего."
        )

    metrics = cross_validate_by_area(features)
    metrics["без_разметки"] = cross_validate_by_area(
        make_features(data, use_annotation=False)
    )["общее"]

    # Финальная модель учится на всех данных — её и используем в пайплайне.
    model = build_model()
    model.fit(features[FEATURE_NAMES], features["label"])

    MODELS.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(model, MODEL_FILE)
    write_report(metrics, model, data)

    print(json.dumps(metrics["общее"], ensure_ascii=False, indent=2))
    return metrics


if __name__ == "__main__":
    main()
