"""Data context shared by every page, plus the ticket detail dialog and ticket table."""
import io
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st

import coaching
import engine as E
import store
import targets
import tickets
import ui

SAMPLE = Path(__file__).parent / "data" / "rideops_support_tickets.csv"
READ_ERRORS = (ValueError, KeyError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError)


def settings() -> E.Settings:
    """Policy settings chosen in the sidebar (saved on the server), falling back to the defaults."""
    ss = st.session_state
    base = E.Settings()
    vals = {f: ss.get(f"set_{f}", getattr(base, f)) for f in E.Settings.__dataclass_fields__}
    if "set_eng_sla_hours" not in ss:          # the SLA is saved in the event log, so it survives a restart
        vals["eng_sla_hours"] = store.sla_override(store.read()) or 0
    return E.Settings(**vals)


def prepare(raw: bytes, cfg: E.Settings | None = None):
    """Tickets with every saved action applied. Refreshes when the event log changes."""
    return _prepare(raw, cfg, store.signature())


@st.cache_data(show_spinner="Loading tickets…", max_entries=12)      # every saved action makes a new entry: keep the newest few
def _prepare(raw: bytes, cfg: E.Settings | None, sig: tuple):
    cfg = cfg or E.Settings()
    df = store.apply(E.load(io.BytesIO(raw)), store.read())
    as_of = df.created_at.max().normalize() + pd.Timedelta(hours=23, minutes=59)
    d = E.enrich(df, as_of, cfg)
    score, cut = E.fit_reopen(d[d.settled], cfg.reopen_flag_share)
    att = E.attention(d, score, cut, cfg)
    return d, as_of, att, cut


def coaching_profile(raw: bytes, agent: str, cfg: E.Settings | None = None) -> dict:
    """One agent's 1:1 profile, cached per dataset, settings and event log (see coaching.py)."""
    return _coaching_profile(raw, agent, cfg, store.signature())


@st.cache_data(show_spinner="Preparing 1:1 notes…", max_entries=40)
def _coaching_profile(raw: bytes, agent: str, cfg, sig: tuple) -> dict:
    d, _, att, _ = _prepare(raw, cfg, sig)
    return coaching.profile(d, att, agent)


def backtests(raw: bytes, cfg: E.Settings | None = None):
    return _backtests(raw, cfg, store.signature())


@st.cache_data(show_spinner="Replaying past escalations…", max_entries=6)
def _backtests(raw: bytes, cfg, sig: tuple):
    """Back-tests replay every escalation (about 1 s); cache per dataset so reruns stay instant."""
    d = _prepare(raw, cfg, sig)[0]
    return E.backtest_reopen(d), E.backtest_gate(d), E.backtest_avoidable_score(d)


def goals(raw: bytes, cfg: E.Settings | None = None) -> dict:
    return _goals(raw, cfg, store.signature())


@st.cache_data(show_spinner=False, max_entries=12)
def _goals(raw: bytes, cfg, sig: tuple) -> dict:
    return targets.targets(_prepare(raw, cfg, sig)[0])


@st.cache_data(show_spinner=False, max_entries=12)
def _saved_bytes(dataset_id: int) -> bytes:
    return store.dataset_content(dataset_id) or SAMPLE.read_bytes()


def raw_data() -> bytes:
    """The export in use: a session override (tests), else the dataset saved as active, else the bundled sample."""
    if st.session_state.get("raw"):
        return st.session_state.raw
    key = store.active_key()
    return SAMPLE.read_bytes() if key == store.SAMPLE else _saved_bytes(int(key))


def data_name() -> str:
    ds = store.active_dataset()
    return f"{ds['name']} ({ds['source']}, saved {ds['uploaded_at'].replace('T', ' ')})" if ds else "sample export"


def context() -> SimpleNamespace:
    cfg = settings()
    d, as_of, att, cut = prepare(raw_data(), cfg)
    # go_live_value is only set when the user picks a date; otherwise default to the day after the data ends
    go_live = pd.Timestamp(st.session_state.get("go_live_value") or (as_of + pd.Timedelta(days=1)).date())
    d = d.assign(after_go_live=d.created_at >= go_live)
    key = hash((raw_data(), cfg, store.active_key()))
    if st.session_state.get("registry_for") != key:
        saved = store.load_registry()     # the registry saved for this dataset, if anyone saved one
        st.session_state.registry = saved if saved is not None else E.seed_registry(d, as_of, cfg)
        st.session_state.registry_for = key
    return SimpleNamespace(d=d, as_of=as_of, att=att, reopen_cut=cut, go_live=go_live, base=E.scorecard(d), cfg=cfg,
                           settle_days=E.settle_days(E.load(io.BytesIO(raw_data()))),
                           targets=goals(raw_data(), cfg))


def flash(message: str, icon: str) -> None:
    """Queue a toast that survives st.rerun()."""
    st.session_state.flash = (message, icon)


def show_flash() -> None:
    msg = st.session_state.pop("flash", None)
    if msg:
        st.toast(msg[0], icon=msg[1])


# ---------- ticket detail ----------

def _fmt_ts(v):
    return "–" if pd.isna(v) else f"{v:%d %b %Y, %H:%M}"


TABLE_CONFIG = {
    "ticket_id": st.column_config.TextColumn("Ticket", width="small", pinned=True),
    "eng_hours": st.column_config.NumberColumn("Hours with eng", format="%.1f"),
    "lag_delay_h": st.column_config.NumberColumn("Hours over limit", format="%.0f"),
    "lag_basis": st.column_config.TextColumn("Basis"),
    "attention_score": st.column_config.ProgressColumn("Attention", help="Adds up the flag weights: higher means act sooner. "
                                                       "Weights are on the Methodology page.", min_value=0,
    max_value=int(sum(E.FLAG_WEIGHTS.values())), format="%d"),
    "flag_list": st.column_config.ListColumn("Flags", width="large"),
    "age_h": st.column_config.NumberColumn("Age (h)", format="%.0f", help="Hours since the ticket was created, at the export's last time."),
    "ttr_h": st.column_config.NumberColumn("Hours to close", format="%.0f"),
    "created_at": st.column_config.DatetimeColumn("Created", format="DD MMM YYYY, HH:mm"),
    "eng_handoffs": st.column_config.NumberColumn("Handoffs", format="%d"),
    "description": st.column_config.TextColumn("Description", width="large"),
    "client_name": st.column_config.TextColumn("Client"), "assigned_agent": st.column_config.TextColumn("Agent"),
    "priority": st.column_config.TextColumn("Priority", width="small"), "status": st.column_config.TextColumn("Status"),
    "category": st.column_config.TextColumn("Category"), "eng_outcome": st.column_config.TextColumn("Eng outcome"),
    "return_reason": st.column_config.TextColumn("Return reason"), "eng_ticket_id": st.column_config.TextColumn("Eng ticket"),
}


def actor(default: str | None = None) -> str:
    """Who is recorded on an action: the signed-in person, else `default`, else the role chosen in the sidebar."""
    user = st.session_state.get("user")
    if user:
        return user["name"][:60]
    return default or st.session_state.get("role_value", "All views")


def _arm(key: str, on: bool) -> None:
    st.session_state[key] = on


def confirm_button(label: str, key: str, message: str, *, icon: str | None = None, type: str = "secondary",
                   disabled: bool = False, help: str | None = None, width: str = "content") -> bool:
    """A button that asks first. The first click shows the message with Confirm and Cancel; True is returned only on
    Confirm. Used for every action that writes to the shared log. Works inside popups (no nested dialog)."""
    armed = f"{key}__armed"
    if not st.session_state.get(armed):
        st.button(label, key=key, icon=icon, type=type, disabled=disabled, help=help, width=width,
                  on_click=_arm, args=(armed, True))
        return False
    st.warning(message, icon=":material/help:")
    yes, no = st.columns(2)
    done = yes.button("Confirm", key=f"{key}__yes", type="primary", width="stretch", icon=":material/check:")
    no.button("Cancel", key=f"{key}__no", width="stretch", on_click=_arm, args=(armed, False))
    if done:      # not in a callback: callbacks run before the script, which would hide this branch before it returns True
        st.session_state[armed] = False
    return done


def undo_control(ticket_id: str, key: str) -> None:
    """Offer to take back the latest action on a ticket (only the latest can be undone)."""
    last = store.last_for_ticket(store.read(), ticket_id)
    if not last:
        return
    if confirm_button(f"Undo: {tickets.describe(last)[:48]}", f"{key}_undo", "This takes the action back for everyone. "
                      "It stays in the history with your name.", icon=":material/undo:"):
        store.undo(last["id"], actor())
        flash("Action taken back", ":material/undo:")
        st.rerun()


def render_ticket(ticket_id: str) -> None:
    """Ticket detail body, shared by the detail popup and the drill-down lists (popups cannot open popups)."""
    c = context()
    row = c.d[c.d.ticket_id.eq(ticket_id)]
    if row.empty:
        ui.empty_state("Ticket not found", f"No ticket with ID {ticket_id} in the loaded data.")
        return
    t = row.iloc[0]
    h = tickets.history(c.d, t)
    hit = c.att.loc[c.att.ticket_id.eq(ticket_id), "flags"]
    flags = [f for f in hit.iloc[0].split("; ") if f] if len(hit) else []
    st.markdown(f"### {t.ticket_id} · {t.client_name}")
    st.html(f'<p class="rx-lead">{escape(t.description)}</p>')
    badges = ui.badge(t.priority, "warn" if t.priority in ("P1", "P2") else "neutral") + " " +         ui.badge(t.status.replace("Open - ", "").capitalize() if t.is_open else "Closed", "bad" if t.is_open else "good")
    if t.reopened:
        badges += " " + ui.badge(f"Reopened ×{int(t.reopen_count)}", "bad")
    if t.eng_lag:
        badges += " " + ui.badge("Engineering lag", "bad")
    if pd.notna(t.call_held_at):
        badges += " " + ui.badge("Call held", "good")
    st.html(badges + " " + " ".join(ui.badge(E.short_flag(f), "bad" if f.startswith("Call") else "warn", E.FLAG_HELP.get(f, ""))
                                    for f in flags))
    pairs = [("Client", f"{t.client_name} ({t.client_tier})"), ("Category", t.category), ("Channel", t.channel),
             ("Agent", t.assigned_agent), ("Ball is with", tickets.owner(t)), ("Created", _fmt_ts(t.created_at)),
             ("First response", _fmt_ts(t.first_response_at)), ("First closed", _fmt_ts(t.first_closed_at)),
             ("Final close", _fmt_ts(t.final_closed_at))]
    if t.esc:
        pairs += [("Engineering ticket", f"{t.eng_ticket_id} · {int(t.eng_handoffs)} handoff(s)"),
                  ("Engineering outcome", t.eng_outcome if pd.notna(t.eng_outcome) else "Pending")]
    if t.tracked:
        pairs.append(("Time with engineering", f"{t.eng_hours:.1f} h (limit {t.eng_sla_h:.0f} h)"))
    if pd.notna(t.call_held_at):
        pairs.append(("Call held", f"{_fmt_ts(t.call_held_at)} with {t.call_held_with}"))
    if pd.notna(t.eng_head_at):
        pairs.append(("Escalated to engineering head", _fmt_ts(t.eng_head_at)))
    if pd.notna(t.csat_score):
        pairs.append(("CSAT", f"{t.csat_score:.0f} / 5"))
    ui.fields(pairs)
    moves = tickets.next_moves(t, flags, c.cfg)
    if moves:
        st.markdown("**Next move**")
        st.markdown("\n".join(f"- {m}" for m in moves))
    st.markdown("**This issue before**")
    if h["peers"]:
        oc = ", ".join(f"{k}: {n}" for k, n in h["outcomes"].items())
        st.markdown(f"Seen {h['peers']} times before. Escalated {ui.pct(h['esc_rate'], 0)} of the time. Median close "
                    f"{ui.hours(h['med_l1'])} at L1, {ui.hours(h['med_esc'])} when escalated." + (f"  \nEngineering verdicts: {oc}." if oc else ""))
        if len(h["recent"]):
            st.warning("Same issue escalated in the week before: " + ", ".join(
                f"{r.eng_ticket_id} ({r.client_name}, {r.eng_outcome if pd.notna(r.eng_outcome) else 'still open'})"
                for r in h["recent"].itertuples()) + ". Ask engineering whether it is one root cause.", icon=":material/link:")
    else:
        st.caption("No earlier tickets with this description.")
    log = tickets.timeline(store.read(), ticket_id)
    if log:
        st.markdown("**Activity in this app**")
        st.markdown("\n".join(f"- {at} · {by}: {txt}" for at, by, txt in log))
    undo_control(ticket_id, f"td_{ticket_id}")
    ss = st.session_state
    left, right = st.columns(2)
    if t.is_open and "desk" in ss.get("allowed_pages", []) and left.button(
            "Open in My desk", key=f"to_desk_{ticket_id}", icon=":material/inbox:", width="stretch"):
        ss.desk_pending = ticket_id
        st.switch_page(ss.pages["desk"])


@ui.popup("Ticket details")
def ticket_dialog(ticket_id: str) -> None:
    render_ticket(ticket_id)


LIST_COLS = ["ticket_id", "status", "priority", "age_h", "category", "description", "client_name", "assigned_agent"]


def show_ticket_list(title: str, ids: list, key: str, columns: list | None = None) -> None:
    """Popup with exactly the tickets behind a number. Selecting one opens its detail inside the same popup."""
    ids = list(dict.fromkeys(ids))

    @ui.popup(title)
    def _body():
        ss = st.session_state
        open_id = ss.get(f"tl_{key}")
        if open_id:
            if st.button("Back to the list", key=f"tl_back_{key}", icon=":material/arrow_back:"):
                ss.pop(f"tl_{key}")
                st.rerun(scope="fragment")
            render_ticket(open_id)
            return
        d = context().d
        view = d[d.ticket_id.isin(ids)].sort_values("age_h", ascending=False)
        st.caption(f"{len(view):,} tickets · select one to open it")
        cols = [c for c in (columns or LIST_COLS) if c in view]
        ev = st.dataframe(view[cols], hide_index=True, height=360, width="stretch", on_select="rerun",
                          selection_mode="single-row", key=f"tl_df_{key}", column_config=TABLE_CONFIG)
        if ev.selection.rows:
            ss[f"tl_{key}"] = view.iloc[ev.selection.rows[0]].ticket_id
            st.rerun(scope="fragment")

    _body()


def ticket_cards(cards: list, key: str) -> None:
    """KPI cards that open their tickets. cards: {label, ids, note}; the number shown is len(ids), so card and list agree."""
    cols = st.columns(len(cards), gap="small")
    for i, (col, card) in enumerate(zip(cols, cards)):
        n = len(set(card["ids"]))
        with col, st.container(key=f"tcard_{key}_{i}"):      # the icon button is placed in the card's top-right corner (CSS)
            ui.kpis([{"label": card["label"], "value": f"{n:,}", "note": card.get("note", "")}])
            if st.button("View tickets", key=f"{key}_card_{i}", type="tertiary", icon=":material/list:",
                         disabled=n == 0, help=f"List the {n} tickets behind “{card['label']}”"):
                show_ticket_list(card["label"], card["ids"], f"{key}_{i}", card.get("columns"))


def ticket_table(df: pd.DataFrame, columns: list, key: str, *, height: int = 420, bulk: bool = True,
                 pick_key: str | None = None) -> None:
    """Selectable ticket table. One row opens the detail dialog; several rows enable bulk actions."""
    if df.empty:
        ui.empty_state("No tickets match", "Clear or change the filters above.")
        return
    cfg = TABLE_CONFIG
    view = df.copy()
    if "flags" in view:
        view["flag_list"] = view["flags"].str.split("; ").apply(lambda x: [E.short_flag(f) for f in x if f])
    cols = ["flag_list" if c == "flags" else c for c in columns]
    if st.session_state.get("plain_tables"):
        ids = view.ticket_id.tolist()
        ui.plain_table(view[cols], cfg, caption="Tickets")
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        chosen = c1.selectbox("Open a ticket", ids[:ui.PLAIN_ROWS], key=f"{key}_plain_pick")
        if c2.button("Open", key=f"{key}_plain_open", width="stretch", icon=":material/open_in_new:"):
            if pick_key:
                st.session_state[pick_key] = chosen
                st.rerun()
            ticket_dialog(chosen)
        st.caption(f"{len(view):,} tickets")
        return
    # Selection is stored as row positions. Tie the widget key to the exact rows shown so a filter change
    # starts a fresh selection instead of re-pointing old positions at different tickets.
    rows_key = f"{key}_{hash(tuple(view.ticket_id)) & 0xFFFFFFFF:x}"
    ev = st.dataframe(view[cols], key=rows_key, hide_index=True, height=height, column_config=cfg, width="stretch",
                      on_select="rerun", selection_mode="multi-row" if bulk else "single-row")
    rows = [r for r in (ev.selection.rows if ev else []) if r < len(view)]
    picked = view.iloc[rows]
    # open details only when the user has just selected a single new row, not when trimming a multi-selection
    now, before = set(picked.ticket_id), st.session_state.get(f"{key}_prev", set())
    if len(now) == 1 and not now <= before:
        if pick_key:                                   # the page acts on this row, so no popup
            st.session_state[pick_key] = next(iter(now))
        else:
            ticket_dialog(next(iter(now)))
    st.session_state[f"{key}_prev"] = now
    bar = st.container(horizontal=True, gap="small", vertical_alignment="center")
    bar.caption(f"{len(view):,} tickets · select one row " + ("to act on it" if pick_key else "for details")
                + (", several for bulk actions" if bulk else ""))
    if bulk and len(picked) > 1:
        bar.download_button(f"Export {len(picked)} selected", picked[[c for c in columns if c != "flags"]]
                            .to_csv(index=False).encode(), file_name=f"{key}_selected.csv", mime="text/csv",
                            icon=":material/download:", on_click="ignore")
        if bar.button(f"Draft client update ({len(picked)})", icon=":material/mail:", key=f"{key}_draft"):
            client_update_dialog(picked.ticket_id.tolist())


@ui.popup("Draft client updates")
def client_update_dialog(ids: list) -> None:
    c = context()
    rows = c.d[c.d.ticket_id.isin(ids)]
    st.caption("One message per ticket, ready to paste into the client's channel. Edit before sending.")
    for _, t in rows.iterrows():
        where = "with our engineering team" if t.status == "Open - with Engineering" else "with our support team"
        st.markdown(f"**{t.ticket_id} · {t.client_name}**")
        st.code(f"Hi {t.client_name} team, an update on {t.ticket_id} ({t.description}). "
                f"It is currently {where}. We will update you again as soon as there is news.", language=None, wrap_lines=True)
