# -*- coding: utf-8 -*-
"""ГОРИЗОНТ — интерфейс сервиса поиска слабых технологических сигналов.

Запуск из корня проекта:  streamlit run src/app/streamlit_app.py

Страница ничего не считает сама: вызывает pipeline.run(query) и рисует
пришедший результат в формате из раздела «Договорённости».
Оформление вынесено в src/app/ui.py.
"""

import os
import sys
import time

import streamlit as st

# Корень проекта нужен в пути: пайплайн импортирует себя как src.collect,
# src.model и так далее — то есть от корня, а не от своей папки.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for path in (ROOT, os.path.join(ROOT, "src"), os.path.dirname(os.path.abspath(__file__))):
    if path not in sys.path:
        sys.path.insert(0, path)

import pipeline          # noqa: E402
import ui                # noqa: E402

st.set_page_config(
    page_title="Горизонт — поиск слабых сигналов",
    page_icon="📡",
    layout="wide",
    # auto: на компьютере панель фильтров открыта, на телефоне свёрнута
    # и не закрывает страницу.
    initial_sidebar_state="auto",
)
st.markdown(ui.CSS, unsafe_allow_html=True)

PRESETS = [
    "слабые сигналы в кибербезопасности",
    "перспективные решения в финтехе",
    "зарождающиеся технологии в робототехнике",
]

if "result" not in st.session_state:
    st.session_state.result = None
if "query" not in st.session_state:
    st.session_state.query = ""
if "error" not in st.session_state:
    st.session_state.error = None
if "q_input" not in st.session_state:
    st.session_state.q_input = ""


def _reset():
    """Кнопка «Новый поиск»: чистая страница без перезагрузки."""
    st.session_state.result = None
    st.session_state.error = None
    st.session_state.query = ""
    st.session_state.q_input = ""


def _preset(text):
    """Готовый запрос: подставляем в поле и запускаем поиск на этом же проходе."""
    st.session_state.q_input = text
    st.session_state.pending = text


# Разные пайплайны называют счётчики по-разному. Приводим к одному виду,
# а чего нет — считаем сами по карточкам, чтобы плашки никогда не пустовали.
KEY_ALIASES = {
    "кандидатов": "candidates",
    "обработано_источников": "processed",
    "показано_источников": "shown",
    "уверенность_выше_75": "high",
    "candidates_found": "candidates",
    "sources_processed": "processed",
    "unique_sources_used": "shown",
    "high_confidence": "high",
}


def normalize(raw, elapsed):
    """Приводим ответ пайплайна к одному виду.

    Ядро отдаёт список карточек и считает счётчики функцией stats().
    Принимаем и словарь — на случай, если контракт поменяется.
    """
    if isinstance(raw, dict):
        cands = raw.get("candidates", [])
        st_raw = raw.get("stats", {})
    else:
        cands = raw or []
        st_raw = pipeline.stats(cands) if hasattr(pipeline, "stats") else {}

    stats = {KEY_ALIASES.get(k, k): v for k, v in st_raw.items()}

    # то, что всегда можно посчитать по карточкам, если пайплайн промолчал
    unique_sources = {
        d.get("source_id")
        for c in cands for d in (c.get("sources") or [])
        if d.get("source_id")
    }
    stats.setdefault("candidates", len(cands))
    stats.setdefault("shown", len(unique_sources))
    stats.setdefault(
        "high",
        sum(1 for c in cands
            if c.get("verdict") == "сигнал" and c.get("score", 0) > 0.75),
    )

    # ТЗ просит количество обработанных источников. Если пайплайн его знает —
    # показываем его, иначе честно пишем, что это только видимые в карточках.
    if stats.get("processed"):
        stats["sources"] = stats["processed"]
        stats["sources_label"] = "обработано источников"
    else:
        stats["sources"] = stats["shown"]
        stats["sources_label"] = "источников в выдаче"

    stats["elapsed"] = f"{elapsed:.1f} с"
    return cands, stats


def search(q):
    q = (q or "").strip()
    if not q:
        st.warning("Введите технологическое направление.")
        return
    started = time.perf_counter()
    # Живой поиск идёт пару минут: показываем, на каком он этапе.
    with st.status("Проверяем, есть ли готовый ответ…", expanded=False) as status:
        try:
            raw = pipeline.run(q, progress=lambda текст: status.update(label=текст))
        except Exception as error:
            status.update(label="Поиск не удался", state="error")
            st.session_state.result = None
            st.session_state.error = str(error)
            st.session_state.query = q
            return
        прошло = time.perf_counter() - started
        status.update(label=f"Готово за {прошло:.0f} с", state="complete")
    st.session_state.error = None
    st.session_state.result = normalize(raw, прошло)
    st.session_state.query = q


# ------------------------------------------------------------------ боковая
with st.sidebar:
    st.markdown("#### Фильтры выдачи")
    min_conf = st.slider("Минимальная уверенность, %", 0, 100, 0, step=5)
    only_trusted = st.checkbox(
        "Только с источником высокого уровня", value=False,
        help="Оставить технологии, у которых есть хотя бы один источник высокой "
             "доверенности: наука, госорганы, университеты, ассоциации.",
    )
    st.markdown("---")
    st.markdown("#### Уровни доверенности")
    st.markdown(
        '<div style="font-size:.82rem;line-height:1.7;color:#475467">'
        '<b style="color:#0E7C5A">высокий</b> — наука, госорганы, международные '
        'организации, университеты, ассоциации<br>'
        '<b style="color:#9A6700">средний</b> — отраслевые медиа, аналитика, '
        'сайты компаний<br>'
        '<b style="color:#B42318">низкий</b> — пресс-релизы, агрегаторы, каталоги, '
        'соцсети</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Источник низкого уровня не может быть единственным основанием "
        "для включения технологии в выдачу."
    )

# ------------------------------------------------------------------ шапка
col_brand, col_new = st.columns([5, 1], vertical_alignment="center")
with col_brand:
    st.markdown(ui.header_html(), unsafe_allow_html=True)
with col_new:
    if st.session_state.result is not None or st.session_state.error:
        st.button("Новый поиск", on_click=_reset, use_container_width=True,
                  type="secondary")
st.markdown(ui.lede_html(), unsafe_allow_html=True)

# Форма: поиск запускается и кнопкой, и клавишей Enter. Раньше Enter только
# перерисовывал страницу со старой выдачей, и казалось, что поиск сломан.
with st.form("search_form", border=False):
    col_in, col_go = st.columns([6, 1])
    with col_in:
        st.text_input(
            "Запрос", key="q_input",
            placeholder="Введите технологическое направление в свободной форме",
            label_visibility="collapsed",
        )
    with col_go:
        go = st.form_submit_button("Найти", use_container_width=True, type="primary")

for col, preset in zip(st.columns(len(PRESETS)), PRESETS):
    col.button(preset, key=f"p_{preset}", use_container_width=True,
               on_click=_preset, args=(preset,))

pending = st.session_state.pop("pending", None)
if go or pending:
    search(st.session_state.q_input if go else pending)
    # Перерисовываем страницу уже с результатом, чтобы в шапке сразу
    # появилась кнопка «Новый поиск».
    st.rerun()

if st.session_state.error:
    st.error(
        "Не удалось выполнить поиск: источник не ответил или закончился лимит "
        "запросов. Попробуйте готовый запрос выше — такие направления "
        "прогреты заранее и открываются из кеша."
    )
    with st.expander("Техническая информация"):
        st.code(st.session_state.error)
    st.stop()

result = st.session_state.result
if result is None:
    st.markdown(
        '<div class="hz-body" style="margin-top:2rem;color:#667085">'
        'Введите направление и нажмите «Найти» либо выберите готовый запрос выше.'
        '</div>', unsafe_allow_html=True)
    st.stop()

# ------------------------------------------------------------------ разбор
candidates, stats = result
if not candidates:
    st.warning("По этому направлению ничего не найдено. Попробуйте переформулировать запрос.")
    st.stop()
signals = [c for c in candidates if c["verdict"] == "сигнал"]
rejected = [c for c in candidates if c["verdict"] == "отклонено"]


def passes(c):
    if int(round(c["score"] * 100)) < min_conf:
        return False
    if only_trusted and not any(s.get("trust") == "высокий" for s in c["sources"]):
        return False
    return True


shown = [c for c in signals if passes(c)][:15]   # ТОП-15 по требованию ТЗ
hidden = len(signals) - len(shown)

st.markdown(
    f'<div class="hz-body" style="margin:.3rem 0 1rem 0;color:#667085">'
    f'Запрос: <b style="color:#101828">{ui.esc(st.session_state.query)}</b></div>',
    unsafe_allow_html=True,
)
st.markdown(ui.stats_html(stats), unsafe_allow_html=True)
if stats.get("processed") and stats.get("shown"):
    st.caption(
        f'В карточках показано {stats["shown"]} документов из '
        f'{stats["processed"]} обработанных — в каждую карточку попадают '
        f'только самые показательные подтверждения.'
    )

tab_sig, tab_rej, tab_method = st.tabs(
    [f"Слабые сигналы · {len(shown)}",
     f"Отклонено · {len(rejected)}",
     "Методология"]
)

with tab_sig:
    if hidden:
        st.caption(f"Скрыто фильтрами: {hidden}")
    if not shown:
        st.warning("Под заданные фильтры не попал ни один кандидат.")
    for i, c in enumerate(shown, 1):
        st.markdown(ui.signal_card_html(i, c), unsafe_allow_html=True)
        with st.expander("Открыть отчёт по технологии"):
            st.markdown(ui.report_html(c), unsafe_allow_html=True)

with tab_rej:
    st.markdown(
        '<div class="hz-body" style="margin-bottom:1rem;color:#667085">'
        'Кандидаты, исключённые из выдачи. Показываем их намеренно: логика отсева '
        'зрелых технологий, маркетингового хайпа и информационного шума — '
        'отдельная часть методологии и отдельный критерий оценки.</div>',
        unsafe_allow_html=True,
    )
    if not rejected:
        st.info("По этому запросу ничего не отсеяно.")
    for c in rejected:
        st.markdown(ui.rejected_html(c), unsafe_allow_html=True)

with tab_method:
    st.markdown(
        """
<div class="hz-sec">Что считается слабым сигналом</div>
<div class="hz-body">Ранняя стадия развития, быстрый рост внимания при небольшой
абсолютной базе упоминаний, немного независимых организаций, отсутствие
утверждённого стандарта и выраженного лидера.</div>

<div class="hz-sec">Восемь признаков</div>
<div class="hz-body">Слова ранней стадии, возраст темы, рост публикаций
за двенадцать месяцев, число организаций, доля лидера, доля доверенных
источников, упоминание стандарта, признак «только медиа». Модель линейная,
поэтому вклад каждого признака читается напрямую и показывается в карточке.</div>

<div class="hz-sec">Что исключается</div>
<div class="hz-body">Зрелые технологии со сформированным рынком, маркетинговый
хайп и информационный шум. Причина по каждому кандидату видна во вкладке
«Отклонено».</div>

<div class="hz-sec">Доверенность источников</div>
<div class="hz-body">Три уровня. Разметка сделана вручную по справочнику доменов,
спорные случаи проверены поштучно, решения задокументированы. Отдельно ведётся
список изданий, которые не используются вовсе — например, клоны научных
журналов, публикующие статьи за деньги под чужим ISSN.</div>

<div class="hz-sec">Ограничения</div>
<div class="hz-body">Выдача строится только по документам, найденным в открытых
источниках; знания языковой модели самостоятельным основанием не являются.
Отсутствие источников высокого уровня не ведёт к отсеву: по ранним темам
научных публикаций часто ещё нет, такие наблюдения получают пониженную
уверенность.</div>
""",
        unsafe_allow_html=True,
    )

st.markdown(
    '<div style="margin-top:3rem;padding-top:1.2rem;border-top:1px solid #E4E7EC;'
    'font-size:.78rem;color:#98A2B3">Горизонт · команда negentropy · ЛЦТ 2026 · '
    'кейс Газпромбанк.Тех</div>',
    unsafe_allow_html=True,
)
