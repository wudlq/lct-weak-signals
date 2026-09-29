# -*- coding: utf-8 -*-
"""Оформление интерфейса: стили и готовые блоки.

Вынесено отдельно, чтобы app.py оставался читаемым: там логика страницы,
здесь — как она выглядит.
"""

import html

# ----------------------------------------------------------------- палитра
BRAND = "#0B3B6F"
INK = "#101828"
MUTED = "#667085"
LINE = "#E4E7EC"

TRUST_COLORS = {
    "высокий": ("#0E7C5A", "#E7F4EF"),
    "средний": ("#9A6700", "#FDF5E6"),
    "низкий": ("#B42318", "#FDECEA"),
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"], .stMarkdown, .stTextInput input, .stButton button {
    font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif;
}

/* убираем фирменные элементы Streamlit, чтобы страница не выглядела шаблонной */
#MainMenu, footer, header [data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stDecoration"] { display: none; }
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1180px; }

/* ---------------------------------------------------------------- шапка */
.hz-brand {
    display: flex; align-items: baseline; gap: .6rem; margin-bottom: .15rem;
}
.hz-brand .mark {
    font-size: 1.45rem; font-weight: 700; letter-spacing: -.02em; color: #0B3B6F;
}
.hz-brand .mark::before {
    content: ""; display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    background: #0B3B6F; margin-right: .5rem; vertical-align: middle;
    box-shadow: 0 0 0 4px rgba(11,59,111,.13);
}
.hz-brand .sub {
    font-size: .8rem; color: #667085; font-weight: 500; letter-spacing: .01em;
}
.hz-lede {
    color: #475467; font-size: .93rem; line-height: 1.55; max-width: 74ch;
    margin: .35rem 0 1.5rem 0;
}

/* ------------------------------------------------------------- плашки */
.hz-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin: .2rem 0 1.6rem 0; }
.hz-stat {
    background: #FFFFFF; border: 1px solid #E4E7EC; border-radius: 12px;
    padding: .95rem 1.05rem; box-shadow: 0 1px 2px rgba(16,24,40,.04);
}
.hz-stat .v { font-size: 1.65rem; font-weight: 700; color: #101828; letter-spacing: -.02em; line-height: 1.1; }
.hz-stat .k { font-size: .76rem; color: #667085; margin-top: .3rem; font-weight: 500; }
.hz-stat.accent { border-color: #C9DAF0; background: linear-gradient(180deg,#F5F9FE 0%,#FFFFFF 100%); }
.hz-stat.accent .v { color: #0B3B6F; }

@media (max-width: 860px) { .hz-stats { grid-template-columns: repeat(2, 1fr); } }

/* ------------------------------------------------------------ карточка */
.hz-card {
    background: #FFFFFF; border: 1px solid #E4E7EC; border-radius: 14px;
    padding: 1.15rem 1.3rem 1.05rem 1.3rem; margin-bottom: .55rem;
    box-shadow: 0 1px 2px rgba(16,24,40,.04);
    border-left: 4px solid var(--accent, #0B3B6F);
}
.hz-rank {
    display: inline-block; min-width: 1.6rem; height: 1.6rem; line-height: 1.6rem;
    text-align: center; border-radius: 6px; background: #EEF3F9; color: #0B3B6F;
    font-size: .8rem; font-weight: 700; margin-right: .55rem;
}
.hz-title { font-size: 1.06rem; font-weight: 650; color: #101828; line-height: 1.4; }

.hz-conf { margin: .85rem 0 .7rem 0; }
.hz-conf .row { display: flex; justify-content: space-between; font-size: .76rem; color: #667085; margin-bottom: .32rem; font-weight: 500; }
.hz-conf .row b { color: #101828; font-weight: 700; font-size: .84rem; }
.hz-track { height: 7px; background: #EFF1F4; border-radius: 99px; overflow: hidden; }
.hz-fill { height: 100%; border-radius: 99px; }

.hz-meta { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .25rem; }
.hz-chip {
    font-size: .73rem; padding: .22rem .6rem; border-radius: 99px;
    background: #F2F4F7; color: #344054; font-weight: 500; white-space: nowrap;
}
.hz-chip.b { background: #EEF3F9; color: #0B3B6F; }

.hz-pred-h { font-size: .74rem; text-transform: uppercase; letter-spacing: .06em;
    color: #667085; font-weight: 600; margin: .95rem 0 .45rem 0; }
.hz-pred { display: flex; flex-direction: column; gap: .3rem; }
.hz-pred div { font-size: .86rem; color: #344054; padding-left: 1rem; position: relative; line-height: 1.45; }
.hz-pred div::before {
    content: ""; position: absolute; left: .18rem; top: .55rem;
    width: 5px; height: 5px; border-radius: 50%; background: #98A2B3;
}

/* ------------------------------------------------------------ источники */
.hz-src { border-top: 1px solid #EFF1F4; padding: .7rem 0 .2rem 0; }
.hz-src:first-of-type { border-top: none; }
.hz-src a { color: #0B3B6F; text-decoration: none; font-weight: 600; font-size: .9rem; }
.hz-src a:hover { text-decoration: underline; }
.hz-src .meta { font-size: .76rem; color: #667085; margin-top: .28rem; line-height: 1.5; }
.hz-badge {
    display: inline-block; font-size: .69rem; font-weight: 700; padding: .13rem .48rem;
    border-radius: 5px; margin-left: .45rem; vertical-align: middle; letter-spacing: .01em;
}
.hz-warn { color: #B42318; font-weight: 600; }

/* ------------------------------------------------------------ отклонено */
.hz-rej {
    background: #FFFFFF; border: 1px solid #E4E7EC; border-left: 4px solid #D0D5DD;
    border-radius: 12px; padding: .85rem 1.1rem; margin-bottom: .55rem;
}
.hz-rej .t { font-weight: 650; color: #101828; font-size: .95rem; }
.hz-rej .r { font-size: .78rem; color: #B42318; font-weight: 600; margin-top: .15rem; }
.hz-rej .d { font-size: .85rem; color: #475467; margin-top: .4rem; line-height: 1.5; }

/* --------------------------------------------------------------- прочее */
.hz-sec { font-size: .74rem; text-transform: uppercase; letter-spacing: .06em;
    color: #667085; font-weight: 600; margin: 1.1rem 0 .4rem 0; }
.hz-body { font-size: .92rem; color: #344054; line-height: 1.6; }

div[data-testid="stExpander"] details {
    border: 1px solid #E4E7EC !important; border-radius: 12px !important;
    background: #FFFFFF !important; margin-bottom: 1.4rem;
}
div[data-testid="stExpander"] summary { font-size: .85rem !important; font-weight: 600 !important; color: #0B3B6F !important; }

.stButton button {
    background: #0B3B6F; color: #fff; border: none; border-radius: 9px;
    font-weight: 600; font-size: .9rem; padding: .55rem 1rem;
}
.stButton button:hover { background: #09305A; color: #fff; }
.stTextInput input {
    border-radius: 9px !important; border: 1px solid #D0D5DD !important;
    padding: .62rem .85rem !important; font-size: .93rem !important;
}
.stTextInput input:focus { border-color: #0B3B6F !important; box-shadow: 0 0 0 3px rgba(11,59,111,.1) !important; }

div[data-baseweb="tab-list"] { gap: .3rem; border-bottom: 1px solid #E4E7EC; }
button[data-baseweb="tab"] { font-size: .89rem !important; font-weight: 600 !important; }
</style>
"""


def esc(s):
    return html.escape(str(s))


def conf_color(score):
    if score >= 0.75:
        return "#0E7C5A"
    if score >= 0.5:
        return "#9A6700"
    return "#98A2B3"


def header_html():
    return (
        '<div class="hz-brand"><span class="mark">ГОРИЗОНТ</span>'
        '<span class="sub">раннее обнаружение технологических трендов</span></div>'
        '<div class="hz-lede">Сервис находит слабые сигналы — технологии на ранней стадии, '
        'о которых ещё не говорят массово. Зрелые решения, отраслевые стандарты '
        'и маркетинговый хайп отсеиваются, причина исключения видна по каждому кандидату.</div>'
    )


def stats_html(stats):
    cells = [
        (stats.get("sources", "—"), stats.get("sources_label", "обработано источников"), ""),
        (stats.get("candidates", "—"), "кандидатов найдено", ""),
        (stats.get("high", "—"), "уверенность выше 75%", "accent"),
        (stats.get("elapsed", "—"), "время поиска", ""),
    ]
    inner = "".join(
        f'<div class="hz-stat {cls}"><div class="v">{esc(v)}</div>'
        f'<div class="k">{esc(k)}</div></div>'
        for v, k, cls in cells
    )
    return f'<div class="hz-stats">{inner}</div>'


ARROW = {"+": "↑", "-": "↓"}


def _original_line(c):
    """Строка под заголовком карточки.

    Требование ТЗ: у зарубежного материала сохраняется оригинальное название.
    Три случая:
      перевод есть  -> показываем оригинал мелким шрифтом;
      перевода нет  -> честно пишем, что название оригинальное;
      всё на русском -> строки нет.
    """
    original = c.get("technology_original")
    lang = c.get("technology_language")
    style = ('font-size:.78rem;color:#98A2B3;margin:.2rem 0 0 2.15rem')

    if lang == "en":
        return (f'<div style="{style}">оригинальное название, '
                f'<span style="color:#9A6700">перевод недоступен</span></div>')
    if original and original != c.get("technology"):
        return f'<div style="{style}">оригинал: {esc(original)}</div>'
    return ""


def signal_card_html(rank, c):
    """Карточка кандидата. c — Candidate из договорённостей."""
    pct = int(round(c["score"] * 100))
    color = conf_color(c["score"])
    chips = ""
    if c.get("area"):
        chips += f'<span class="hz-chip b">{esc(c["area"])}</span>'
    if c.get("doc_count"):
        chips += f'<span class="hz-chip">подтверждений: {esc(c["doc_count"])}</span>'
    feats = ""
    for f in c.get("top_features", []):
        sign = ARROW.get(f.get("direction", "+"), "")
        val = f.get("value")
        val = "" if val is None else f' <span style="color:#667085">{esc(val)}</span>'
        feats += f'<div>{sign} {esc(f["name"])}{val}</div>'
    return f"""
<div class="hz-card" style="--accent:{color}">
  <div><span class="hz-rank">{rank}</span><span class="hz-title">{esc(c['technology'])}</span></div>
  {_original_line(c)}
  <div class="hz-conf">
    <div class="row"><span>Уверенность модели</span><b>{pct}%</b></div>
    <div class="hz-track"><div class="hz-fill" style="width:{pct}%;background:{color}"></div></div>
  </div>
  <div class="hz-meta">{chips}</div>
  <div class="hz-pred-h">Ключевые признаки</div>
  <div class="hz-pred">{feats}</div>
</div>
"""


def sources_html(sources):
    """sources — список Document из договорённостей."""
    if not sources:
        return '<div class="hz-body" style="color:#98A2B3">Источников нет.</div>'
    out = []
    for s in sources:
        fg, bg = TRUST_COLORS.get(s.get("trust"), ("#344054", "#F2F4F7"))
        badge = (f'<span class="hz-badge" style="color:{fg};background:{bg}">'
                 f'{esc(s.get("trust") or "—")}</span>')
        meta = " · ".join(filter(None, [
            esc(s.get("source_type") or "тип не определён"),
            esc(s.get("published") or "дата не указана"),
            f'язык оригинала: {esc(s.get("language") or "—")}',
            esc(s["venue"]) if s.get("venue") else None,
            ", ".join(esc(o) for o in (s.get("orgs") or [])) or None,
        ]))
        block = (f'<div class="hz-src"><a href="{esc(s.get("url") or "#")}" '
                 f'target="_blank">{esc(s.get("title") or "без названия")}</a>{badge}'
                 f'<div class="meta">{meta}</div>')
        if s.get("ru_summary"):
            note = " <i>(автоматический перевод)</i>" if s.get("translated") else ""
            block += (f'<div class="meta" style="color:#475467;margin-top:.35rem">'
                      f'{esc(s["ru_summary"])}{note}</div>')
        out.append(block + "</div>")
    return "".join(out)


PENDING = ('<span style="color:#98A2B3">готовится модулем текстов</span>')


def _field(c, key):
    v = c.get(key)
    return esc(v) if v else PENDING


def report_html(c):
    pct = int(round(c["score"] * 100))
    return f"""
<div class="hz-sec">Описание технологии</div>
<div class="hz-body">{_field(c, 'description')}</div>
<div class="hz-sec">Потенциальное преимущество</div>
<div class="hz-body">{_field(c, 'advantage')}</div>
<div class="hz-sec">Кейс-пример</div>
<div class="hz-body">{_field(c, 'case_example')}</div>
<div class="hz-sec">Почему модель уверена на {pct}%</div>
<div class="hz-body">Решение принято по перечисленным выше признакам: стрелка вверх
означает вклад в пользу слабого сигнала, вниз — против. Значение показывает,
насколько сильно признак выражен по сравнению с обучающей выборкой.</div>
<div class="hz-sec">Источники</div>
{sources_html(c['sources'])}
"""


REJECT_LABEL = {
    "зрелая": "Зрелая технология",
    "хайп": "Маркетинговый хайп",
    "шум": "Информационный шум",
}


def rejected_html(c):
    reason = REJECT_LABEL.get(c.get("reject_reason"), c.get("reject_reason") or "—")
    why = ", ".join(
        f'{f["name"]} {esc(f.get("value"))}'
        for f in c.get("top_features", []) if f.get("direction") == "-"
    )
    return (
        f'<div class="hz-rej"><div class="t">{esc(c["technology"])}</div>'
        f'<div class="r">{esc(reason)}</div>'
        f'<div class="d">{_field(c, "description")}'
        + (f'<br><span style="color:#667085">Признаки против: {why}</span>' if why else '')
        + '</div></div>'
    )
