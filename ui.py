"""Shared UI components. Every page builds from these so layout, type and colour stay consistent.

All text that can come from data is escaped before it reaches st.html.
"""
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

import tokens as T


def theme() -> str:
    t = getattr(st.context, "theme", None)
    return "dark" if t is not None and getattr(t, "type", None) == "dark" else "light"


def color(name: str) -> str:
    return T.COLORS[theme()][name]


CSS = """
html, body, [data-testid="stAppViewContainer"] { font-variant-numeric: tabular-nums; }
/* top padding clears Streamlit's fixed header (logo + menu button, ~60px) so the page title is never covered */
[data-testid="stMainBlockContainer"] { max-width: var(--layout-max, 1440px); padding: var(--space-10) var(--space-8) var(--space-10); }
@media (max-width: 768px) { [data-testid="stMainBlockContainer"] { padding: var(--space-10) var(--space-4) var(--space-9); } }
h1, h2, h3 { color: var(--color-text-primary); }
:focus-visible { outline: 2px solid var(--color-focus-ring) !important; outline-offset: 2px; }

/* page header */
.rx-desc { color: var(--color-text-secondary); font-size: var(--type-body-size); line-height: var(--type-body-lh); max-width: 78ch; margin: 0; }

/* KPI cards */
/* KPI grid: all cards in one row on wide screens, then 3 / 2 / 1 columns so rows never leave an orphan */
.rx-kpis { display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); gap: var(--space-3); margin: var(--space-1) 0 var(--space-2); }
@media (max-width: 1279px) { .rx-kpis.n6, .rx-kpis.n5 { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1023px) { .rx-kpis.n4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 767px) { .rx-kpis.n6, .rx-kpis.n5, .rx-kpis.n3 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 767px) { .rx-kpis.n4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 359px) { .rx-kpis { grid-template-columns: 1fr !important; } }
/* one anatomy for every card: label (1 line), value, context (1 line); flat, border only */
.rx-kpi { border: 1px solid var(--color-border); border-radius: var(--radius-lg); padding: var(--space-3) var(--space-4) var(--space-4);
  background: var(--color-surface-elevated); min-width: 0; display: flex; flex-direction: column; gap: var(--space-1); }
.rx-kpi-label { font-size: var(--type-caption-size); font-weight: 550; color: var(--color-text-secondary); margin: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rx-kpi-value { font-size: var(--type-metric-size); line-height: var(--type-metric-lh); font-weight: var(--type-metric-weight);
  letter-spacing: var(--type-metric-ls); color: var(--color-text-primary); margin: 2px 0 0; }
.rx-kpi-delta { font-size: var(--type-caption-size); margin: 0; color: var(--color-text-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rx-kpi-delta .rx-good { color: var(--color-success); font-weight: 550; }
.rx-kpi-delta .rx-bad { color: var(--color-danger); font-weight: 550; }
.rx-kpi-delta .rx-neutral { color: var(--color-text-secondary); font-weight: 550; }
.rx-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

/* badges */
.rx-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: var(--radius-pill);
  font-size: var(--type-caption-size); font-weight: 550; line-height: 1.5; white-space: nowrap; }
.rx-badge.good { color: var(--color-success); background: var(--color-success-bg); }
.rx-badge.bad { color: var(--color-danger); background: var(--color-danger-bg); }
.rx-badge.warn { color: var(--color-warning); background: var(--color-warning-bg); }
.rx-badge.info { color: var(--color-info); background: var(--color-info-bg); }
.rx-badge.neutral { color: var(--color-text-secondary); background: var(--color-surface-subtle); }
/* quiet status: coloured dot + text, for tables where many rows share a status */
.rx-status { display: inline-flex; align-items: center; gap: 6px; font-size: var(--type-body-sm-size); font-weight: 550; white-space: nowrap; }
.rx-status::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.rx-status.good { color: var(--color-success); } .rx-status.bad { color: var(--color-danger); }
.rx-status.warn { color: var(--color-warning); } .rx-status.neutral { color: var(--color-text-secondary); }

/* simple semantic table (scorecard targets) */
.rx-table { width: 100%; border-collapse: collapse; font-size: var(--type-body-size); }
.rx-table th { text-align: left; font-size: var(--type-caption-size); font-weight: 600; color: var(--color-text-secondary);
  padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-border); background: var(--color-sidebar); }
.rx-table tr:last-child td { border-bottom: 0; }
.rx-table td { padding: 10px var(--space-3); border-bottom: 1px solid var(--color-border-subtle); color: var(--color-text-primary); vertical-align: top; }
.rx-table td.num, .rx-table th.num { text-align: right; }
.rx-table tr:hover td { background: var(--color-surface-subtle); }
.rx-table-wrap { overflow-x: auto; border: 1px solid var(--color-border); border-radius: var(--radius-lg); }
.rx-muted { color: var(--color-text-muted); font-size: var(--type-body-sm-size); }

/* definition list */
.rx-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--space-3) var(--space-6); margin: var(--space-3) 0; }
.rx-fields dt { font-size: var(--type-caption-size); color: var(--color-text-muted); font-weight: 550; }
.rx-fields dd { margin: 2px 0 0; color: var(--color-text-primary); font-size: var(--type-body-size); }

/* empty state */
.rx-empty { border: 1px dashed var(--color-border); border-radius: var(--radius-lg); padding: var(--space-8) var(--space-6);
  text-align: center; color: var(--color-text-secondary); }
.rx-empty strong { display: block; color: var(--color-text-primary); font-size: var(--type-body-size); font-weight: 600; margin-bottom: 2px; }
.rx-empty.compact { text-align: left; padding: var(--space-3) var(--space-4); border-style: solid; background: var(--color-surface-subtle); border-color: transparent; }
.rx-empty.compact strong { display: inline; margin-right: var(--space-2); }

/* sidebar */
.rx-side-label { font-size: var(--type-label-size); font-weight: var(--type-label-weight); letter-spacing: var(--type-label-ls);
  text-transform: uppercase; color: var(--color-text-muted); margin: var(--space-4) 0 var(--space-1) var(--space-2); }
.rx-side-meta { font-size: var(--type-caption-size); color: var(--color-text-muted); line-height: 1.5; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: var(--space-1); }
[data-testid="stSidebar"] [data-testid="stSelectbox"], [data-testid="stSidebar"] [data-testid="stTextInput"],
[data-testid="stSidebar"] [data-testid="stExpander"] { margin-bottom: var(--space-2); }
.rx-side-label:first-child { margin-top: var(--space-2); }

/* Streamlit draws primary-button text white in both themes: only 2.6:1 on the dark theme's light blue */
[data-testid^="stBaseButton-primary"], [data-testid^="stBaseButton-primary"] * { color: var(--color-on-primary) !important; }

/* section rhythm: headings get room above, captions sit tight under them */
[data-testid="stMainBlockContainer"] h2 { padding-top: var(--space-4); }
/* st.caption dims text to 60% opacity, which drops it below 4.5:1; use the muted token at full strength */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: var(--color-text-muted); opacity: 1; }

/* popups: one size, header and scroll rule everywhere; full-screen on phones */
[data-testid="stDialog"] div[role="dialog"] { width: min(860px, calc(100vw - 2rem)); max-width: none; max-height: calc(100dvh - 2rem);
  overflow-y: auto; border-radius: var(--radius-xl); }
[data-testid="stDialog"] div[role="dialog"] h2 { padding-top: 0; }
@media (max-width: 640px) { [data-testid="stDialog"] div[role="dialog"] { width: 100vw; max-height: 100dvh; border-radius: 0; } }
.rx-lead { font-size: var(--type-body-lg-size, 1.05rem); color: var(--color-text-primary); margin: var(--space-2) 0; }
/* a card with the button that opens its tickets attached underneath */
/* "View tickets" is an icon in the top-right corner of its card; the words stay for screen readers and the tooltip */
[class*="st-key-tcard_"] { position: relative; }
[class*="st-key-tcard_"] [data-testid="stElementContainer"]:has(button) { position: absolute; top: 6px; right: 6px; width: auto; z-index: 1; }
[class*="st-key-tcard_"] button { min-height: 32px; min-width: 32px; width: 32px; height: 32px; padding: 0; }
[class*="st-key-tcard_"] button p { font-size: 0; margin: 0; }
[class*="st-key-tcard_"] .rx-kpi-label { padding-right: 36px; }

/* Streamlit's "?" help icons are 14 px; keep the look but give them a 24 px target (WCAG 2.2 target size) */
button[aria-label^="Help for"] { min-width: 24px; min-height: 24px; display: inline-flex; align-items: center; justify-content: center; }

@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition: none !important; animation: none !important; } }
"""


def inject_css() -> None:
    st.html(f"<style>{T.css_vars(theme())}{CSS}</style>")


TERMS = [
    ("L1", "the first-line support agent who owns a ticket until it goes to engineering."),
    ("Escalation", "sending a ticket to engineering. Each trip counts as a handoff."),
    ("Bounce", "a ticket that went to engineering more than once."),
    ("Return", "engineering sends an escalation back to L1 with a reason code."),
    ("Avoidable escalation", "one engineering returned because information, a setting or a how-to answer was missing, or it was a duplicate or not reproducible."),
    ("North star", "the share of settled tickets closed on time and never reopened."),
    ("Settled", "old enough that a reopen would have shown up, so the ticket can be scored."),
    ("Lane", "the deadline that applies: L1 for tickets not escalated, engineering for escalated ones."),
    ("At-risk account", "a client with several bad experiences recently."),
    ("Call required", "a second escalation: engineer and agent talk instead of returning the ticket."),
]


# ---------- layout ----------

def page_header(section: str, title: str, description: str = ""):
    """H1 and description (the menu already shows where you are; `section` is kept for callers). Returns the actions container."""
    left, right = st.columns([3, 2], vertical_alignment="bottom")
    with left:
        st.markdown(f"# {title}")
        if description:
            st.html(f'<p class="rx-desc">{escape(description)}</p>')
    actions = right.container(horizontal=True, horizontal_alignment="right", gap="small")
    with actions.popover("Terms", icon=":material/menu_book:"):
        st.markdown("**Words used in this app**")
        for term, meaning in TERMS:
            st.markdown(f"**{term}**: {meaning}")
    st.space("small")
    return actions


def section(title: str, caption: str = "") -> None:
    st.markdown(f"## {title}")
    if caption:
        st.caption(caption)


def kpis(cards: list) -> None:
    """cards: dicts with label, value, and optional delta, tone ('good'|'bad'|'neutral'), note."""
    out = []
    for c in cards:
        delta = ""
        if c.get("delta"):
            tone = c.get("tone", "neutral")
            word = {"good": "Improving.", "bad": "Worsening.", "neutral": ""}[tone]
            delta = (f'<p class="rx-kpi-delta"><span class="rx-sr">{word}</span>'
                     f'<span class="rx-{tone}">{escape(c["delta"])}</span> {escape(c.get("note", ""))}</p>')
        else:  # always render the context line so every card has the same anatomy and height
            delta = f'<p class="rx-kpi-delta">{escape(c.get("note", "")) or "&nbsp;"}</p>'
        out.append(f'<div class="rx-kpi" role="group" aria-label="{escape(c["label"])}">'
                   f'<p class="rx-kpi-label" title="{escape(c["label"])}">{escape(c["label"])}</p>'
                   f'<p class="rx-kpi-value">{escape(str(c["value"]))}</p>{delta}</div>')
    st.html(f'<div class="rx-kpis n{len(cards)}" style="--n:{len(cards)}">{"".join(out)}</div>')


def badge(text: str, tone: str = "neutral", title: str = "") -> str:
    tip = f' title="{escape(title)}"' if title else ""
    return f'<span class="rx-badge {tone}"{tip}>{escape(text)}</span>'


def status(text: str, tone: str = "neutral") -> str:
    """Quiet dot + text status for tables, where filled pills on every row become noise."""
    return f'<span class="rx-status {tone}">{escape(text)}</span>'


def html_table(df: pd.DataFrame, numeric: tuple = (), raw_html: tuple = (), caption: str = "") -> None:
    """Small semantic table for summary data. Columns in raw_html must already be escaped/built by us."""
    head = "".join(f'<th scope="col" class="{"num" if c in numeric else ""}">{escape(str(c))}</th>' for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c] if c in raw_html else escape(str(r[c]))
            cells.append(f'<td class="{"num" if c in numeric else ""}">{v}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    cap = f'<caption class="rx-sr">{escape(caption)}</caption>' if caption else ""
    st.html(f'<div class="rx-table-wrap"><table class="rx-table">{cap}<thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


PLAIN_ROWS = 300      # a plain table shows this many rows; the grid view scrolls through all of them


def _label(col: str, cfg: dict) -> str:
    c = (cfg or {}).get(col)
    label = c.get("label") if isinstance(c, dict) else None
    return label or col.replace("_", " ").capitalize()


def _cell(v, fmt: str | None) -> str:
    if v is None or (not isinstance(v, (list, tuple, str)) and pd.isna(v)):
        return "–"
    if isinstance(v, (list, tuple)):
        return ", ".join(map(str, v))
    if isinstance(v, pd.Timestamp):
        return f"{v:%d %b %Y %H:%M}"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if fmt == "percent":
            return f"{v:.1%}"
        if fmt and "%" in fmt:
            try:
                return (fmt % v).replace("%%", "%")
            except (TypeError, ValueError):
                pass
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"
    return str(v)


def plain_table(df: pd.DataFrame, cfg: dict | None = None, caption: str = "") -> None:
    """The same data as a real HTML table: readable by a screen reader, selectable and copyable text."""
    shown = df.head(PLAIN_ROWS)
    labels = {c: _label(c, cfg) for c in shown.columns}
    fmts = {c: ((cfg or {}).get(c) or {}).get("type_config", {}).get("format") if isinstance((cfg or {}).get(c), dict) else None
            for c in shown.columns}
    out = pd.DataFrame({labels[c]: [_cell(v, fmts[c]) for v in shown[c]] for c in shown.columns})
    num = tuple(labels[c] for c in shown.columns if pd.api.types.is_numeric_dtype(shown[c]) and not pd.api.types.is_bool_dtype(shown[c]))
    html_table(out, numeric=num, caption=caption or "Table")
    if len(df) > PLAIN_ROWS:
        st.caption(f"Showing the first {PLAIN_ROWS:,} of {len(df):,} rows. Turn off Plain tables to scroll through all of them, "
                   "or export the data.")


def dataframe(df: pd.DataFrame, **kw):
    """st.dataframe, or a plain HTML table when the sidebar's "Plain tables" switch is on. Tables with row selection stay grids."""
    if st.session_state.get("plain_tables") and "on_select" not in kw:
        df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        order = kw.get("column_order")
        if order:
            df = df[[c for c in order if c in df.columns]]
        if kw.get("hide_index") is False:
            df = df.reset_index()
        plain_table(df, kw.get("column_config"))
        return None
    return st.dataframe(df, **kw)


def fields(pairs: list) -> None:
    """Label / value pairs as a definition list in a responsive two-column grid."""
    items = "".join(f"<div><dt>{escape(str(k))}</dt><dd>{escape(str(v))}</dd></div>" for k, v in pairs)
    st.html(f'<dl class="rx-fields">{items}</dl>')


def empty_state(title: str, body: str, compact: bool = False) -> None:
    """Full empty state for a main table; compact one-line note for secondary sections."""
    cls = "rx-empty compact" if compact else "rx-empty"
    st.html(f'<div class="{cls}" role="status"><strong>{escape(title)}</strong><span class="rx-muted">{escape(body)}</span></div>')


def hours(x) -> str:
    return "–" if pd.isna(x) else f"{x:.0f} h" if x < 48 else f"{x / 24:.1f} days"


def popup(title: str, *, icon: str | None = None, on_dismiss="ignore"):
    """Every popup in the app: same width, header, close button, Esc and scrolling (see the dialog rules in CSS)."""
    return st.dialog(title, width="large", icon=icon, on_dismiss=on_dismiss)


def pct(x, digits: int = 1) -> str:
    return "–" if pd.isna(x) else f"{x:.{digits}%}"


PCT = "%.1f%%"  # one decimal for every percentage column in data tables


def as_pct(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """Scale rate columns (0–1) to 0–100 for display with PCT."""
    return df.assign(**{c: df[c] * 100 for c in cols if c in df})


# ---------- charts (Altair, themed by Streamlit + explicit series colours) ----------

def _series_scale(domain: list) -> alt.Scale:
    return alt.Scale(domain=domain, range=T.CHART[theme()][:len(domain)])


def _ticks(fmt: str) -> dict:
    # avoid repeated tick labels ("1% 1% 2%") when the format rounds finer ticks
    return {"tickMinStep": 0.01} if fmt == ".0%" else ({"tickMinStep": 1} if fmt == "d" else {})


def line_chart(df: pd.DataFrame, x: str, y: str, y_title: str, description: str, *, fmt: str = ".0%",
               ref: dict | None = None, height: int = 260, area: bool = False):
    """Section heading names the measure, so the y-axis carries no title (it stays in the tooltip)."""
    base = alt.Chart(df).encode(
        x=alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%d %b", labelAngle=0, tickCount=8)),
        y=alt.Y(f"{y}:Q", title=None, axis=alt.Axis(format=fmt, tickCount=5, **_ticks(fmt)), scale=alt.Scale(zero=area)),
        tooltip=[alt.Tooltip(f"{x}:T", title="Week of" if not area else "Date", format="%d %b %Y"),
                 alt.Tooltip(f"{y}:Q", title=y_title, format=fmt)],
    )
    mark = base.mark_area(opacity=0.10, line={"color": color("primary"), "strokeWidth": 1.75}, color=color("primary")) if area \
        else base.mark_line(strokeWidth=2, color=color("primary"), point=alt.OverlayMarkDef(size=24, filled=True))
    layers = [mark]
    for label, (value, tone) in (ref or {}).items():
        rule = alt.Chart(pd.DataFrame({"v": [value], "l": [label]})).mark_rule(
            strokeDash=[4, 4], color=color(tone), strokeWidth=1.5).encode(
            y="v:Q", tooltip=[alt.Tooltip("l:N", title="Reference"), alt.Tooltip("v:Q", title="Value", format=fmt)])
        text = alt.Chart(pd.DataFrame({"v": [value], "l": [label]})).mark_text(
            align="left", dx=4, dy=-6, color=color(tone), fontSize=11).encode(y="v:Q", x=alt.value(0), text="l:N")
        layers += [rule, text]
    chart = alt.layer(*layers).properties(height=height, description=description)
    st.altair_chart(chart, width="stretch", theme="streamlit")


def hbar_chart(df: pd.DataFrame, cat: str, val: str, val_title: str, description: str, *, fmt: str = ".0%",
               ref: tuple | None = None, height: int | None = None, highlight: str | None = None):
    h = height or max(160, 30 * len(df) + 40)
    enc_color = alt.value(color("primary"))
    if highlight:
        enc_color = alt.condition(f"datum['{highlight}']", alt.value(color("danger")), alt.value(color("primary")))
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=3, height={"band": 0.6}).encode(
        y=alt.Y(f"{cat}:N", title=None, sort="-x" if ref is None else None, axis=alt.Axis(labelLimit=220)),  # long names truncate; full text in tooltip
        x=alt.X(f"{val}:Q", title=None, axis=alt.Axis(format=fmt, tickCount=6, **_ticks(fmt)), scale=alt.Scale(nice=True)),
        color=enc_color,
        tooltip=[alt.Tooltip(f"{cat}:N", title=cat.capitalize()), alt.Tooltip(f"{val}:Q", title=val_title, format=fmt)],
    )
    layers = [bars]
    if ref:
        label, value = ref
        layers.append(alt.Chart(pd.DataFrame({"v": [value], "l": [label]})).mark_rule(
            strokeDash=[4, 4], color=color("text-secondary")).encode(
            x="v:Q", tooltip=[alt.Tooltip("l:N", title="Reference"), alt.Tooltip("v:Q", format=fmt, title="Value")]))
    st.altair_chart(alt.layer(*layers).properties(height=h, description=description), width="stretch", theme="streamlit")


def stacked_bar_chart(df: pd.DataFrame, x: str, series: str, val: str, domain: list, description: str,
                      *, y_title: str = "Escalations", height: int = 280):
    # weekly buckets as an ordered band scale, so bars get proper width (a time scale draws hairlines)
    df = df.assign(_wk=pd.to_datetime(df[x]).dt.strftime("%d %b"))
    order = df.sort_values(x)["_wk"].unique().tolist()
    chart = alt.Chart(df).mark_bar(width={"band": 0.7}).encode(
        x=alt.X("_wk:O", title=None, sort=order, axis=alt.Axis(labelAngle=0, labelOverlap="greedy")),
        y=alt.Y(f"sum({val}):Q", title=None, axis=alt.Axis(tickMinStep=1, tickCount=5)),
        color=alt.Color(f"{series}:N", title=None, scale=_series_scale(domain),
                        legend=alt.Legend(orient="top", direction="horizontal", symbolType="square")),
        order=alt.Order(f"{series}:N"),
        tooltip=[alt.Tooltip("_wk:O", title="Week of"), alt.Tooltip(f"{series}:N", title="Reason"),
                 alt.Tooltip(f"sum({val}):Q", title=y_title)],
    ).properties(height=height, description=description)
    st.altair_chart(chart, width="stretch", theme="streamlit")


def data_alternative(df: pd.DataFrame, label: str = "View chart data") -> None:
    """Accessible table alternative for a chart."""
    with st.expander(label, type="compact", icon=":material/table_view:"):
        st.dataframe(df, hide_index=True, width="stretch")
