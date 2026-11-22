"""Support lead: attention queue and agent coaching."""
import pandas as pd
import streamlit as st

import io

import coaching
import engine as E
import state
import store
import ui

# flag -> (short card label, context line)
COUNTED = {
    "Overdue, engineering lane": ("Overdue · engineering", "past the escalated deadline"),
    "Overdue, L1 lane": ("Overdue · L1", "past the L1 deadline"),
    "Returned by eng, waiting on L1": ("Returned to L1", "engineering sent back"),
    "Bounced 2+ times": ("Bounced", "2+ handoffs"),
    "Reopened by client": ("Reopened", "by the client"),
    "No first response": ("No first response", "awaiting L1 reply"),
    "At-risk accounts": ("At-risk accounts", "open tickets of at-risk clients"),
    "Tickets open 7+ days": ("Open 7+ days", "older than a week"),
}


def _clear_filters():
    for k in ("aq_search", "aq_agents", "aq_flags"):
        st.session_state.pop(k, None)


def attention_queue():
    c = state.context()
    att = c.att
    actions = ui.page_header("Support", "Attention queue",
                             "Open tickets ranked by what needs action now. Overdue and returned tickets come first. "
                             "Select a row for details, or several to export or draft client updates.")
    actions.download_button("Export queue", att.drop(columns=list(E.FLAG_WEIGHTS)).to_csv(index=False).encode(),
                            "attention_queue.csv", "text/csv", icon=":material/download:", on_click="ignore")
    cfg = c.cfg
    hours = {"Overdue, engineering lane": f"> {cfg.eng_hours}h, escalated", "Overdue, L1 lane": f"> {cfg.l1_hours}h, not escalated"}
    notes = {"At-risk accounts": f"{cfg.at_risk_min_bad}+ bad experiences in {cfg.at_risk_days} days"}
    cards = [{"label": lab, "ids": att[att[f]].ticket_id.tolist(), "note": hours.get(f, notes.get(f, note))}
             for f, (lab, note) in COUNTED.items()]
    for row in range(0, len(cards), 4):          # the number on a card is the length of the list behind it
        state.ticket_cards(cards[row:row + 4], key=f"aq_cards_{row}")

    f1, f2, f3 = st.columns([2, 2, 1], vertical_alignment="bottom")
    q = f1.text_input("Search", key="aq_search", placeholder="Ticket ID, client or description",
                      icon=":material/search:")
    agents = f2.multiselect("Agent", sorted(att.assigned_agent.unique()), key="aq_agents", placeholder="All agents")
    f3.button("Clear filters", on_click=_clear_filters, icon=":material/filter_alt_off:", width="stretch")
    flags = st.pills("Show tickets with all of these flags", list(E.FLAG_WEIGHTS), selection_mode="multi", key="aq_flags",
                     format_func=E.short_flag)
    with st.expander("What the flags mean", type="compact", icon=":material/help:"):
        st.markdown("\n".join(f"- **{E.short_flag(f)}**: {E.FLAG_HELP[f]}" for f in E.FLAG_WEIGHTS))

    view = att
    if q:
        s = q.strip().lower()
        view = view[view.ticket_id.str.lower().str.contains(s, regex=False)
                    | view.client_name.str.lower().str.contains(s, regex=False)
                    | view.description.str.lower().str.contains(s, regex=False)]
    if agents:
        view = view[view.assigned_agent.isin(agents)]
    for f in flags or []:
        view = view[view[f]]

    state.ticket_table(view, ["ticket_id", "attention_score", "flags", "status", "priority", "age_h", "category",
                              "description", "client_name", "assigned_agent", "eng_handoffs"], key="aq_table")

    _load_and_moves(c)


def _load_and_moves(c) -> None:
    """Load by agent, and suggested moves that appear only when an agent is above the overload line (from Routing and load)."""
    d, att, cfg = c.d, c.att, c.cfg
    agents = sorted(d.assigned_agent.unique())
    open_n = att.groupby("assigned_agent").size().reindex(agents, fill_value=0)
    avg = open_n.mean()
    line = avg * cfg.overload_percent / 100
    last = d.month.max()
    owners = d.groupby(["client_id", "assigned_agent"]).size().reset_index(name="n").sort_values(
        ["client_id", "n"], ascending=[True, False]).drop_duplicates("client_id").assigned_agent.value_counts()
    tbl = pd.DataFrame({"Agent": agents, "Open now": open_n.values,
                        f"Tickets in {pd.Period(last).strftime('%B')}": [int(((d.assigned_agent == a) & (d.month == last)).sum()) for a in agents],
                        "Clients owned": [int(owners.get(a, 0)) for a in agents]})
    ui.section("Load by agent", f"Open now and tickets in {pd.Period(last).strftime('%B')}. An agent is overloaded above "
               f"{cfg.overload_percent}% of the team average ({avg:.1f} open, so above {line:.1f}).")
    ui.dataframe(tbl, hide_index=True, width="stretch")
    ld = tbl[["Agent", "Open now"]]
    ui.hbar_chart(ld, "Agent", "Open now", "Open tickets", "Bar chart of open tickets per agent.", fmt="d")
    over = [a for a in agents if open_n[a] > line]
    ui.section("Suggested moves", "Open L1 tickets from overloaded agents, to the least-loaded agent. Shown only when someone is overloaded.")
    if not over:
        ui.empty_state("No one is overloaded", f"Every agent is within {cfg.overload_percent}% of the team average.", compact=True)
        return
    least = open_n.sort_values().index
    mv = att[att.assigned_agent.isin(over) & att.status.eq("Open - with L1")]
    if mv.empty:
        ui.empty_state("Nothing to move", "The overloaded agents have no open tickets with L1.", compact=True)
    plan = open_n.to_dict()          # keep counting as moves are planned, so they spread out instead of piling on one agent
    for r in mv.itertuples():
        to = min((a for a in least if a != r.assigned_agent), key=lambda a: (plan[a], a))
        plan[to] += 1
        plan[r.assigned_agent] -= 1
        a, b, c3, e = st.columns([2, 4, 3, 2], vertical_alignment="center")
        a.markdown(f"**{r.ticket_id}**")
        b.caption(r.description)
        c3.caption(f"{r.assigned_agent} → {to}")
        if state.confirm_button("Reassign", f"mv_{r.ticket_id}", f"Reassign {r.ticket_id} from {r.assigned_agent} to {to}? "
                                "You can undo it from the ticket afterwards.", icon=":material/swap_horiz:"):
            store.append("ticket.assign", state.actor("Support lead"), {"id": r.ticket_id, "agent": to})
            state.flash(f"{r.ticket_id} reassigned to {to}", ":material/swap_horiz:")
            st.rerun()


def _coaching_overview():
    c = state.context()
    d = c.d
    t = E.agent_table(d)
    actions = ui.page_header("Support", "Agent coaching",
                             "Every agent compared with the others, with the main point to discuss. "
                             "Open an agent's 1:1 prep for the evidence, the tickets to review and an exportable summary.")
    raw = state.raw_data()
    cfg = c.cfg
    agents = sorted(d.assigned_agent.unique())
    heads = {a: coaching.headline_of(state.coaching_profile(raw, a, cfg)) for a in agents}
    t["coaching note"] = [heads[a]["focus"] for a in t.index]
    actions.download_button("Export agent table", t.to_csv().encode(), "agent_coaching.csv", "text/csv",
                            icon=":material/download:", on_click="ignore")
    lm = d.month.max()
    lm_label = pd.Period(lm).strftime("%b %Y")
    load = d[d.month == lm].groupby("assigned_agent").size()
    ratio = load.max() / load.min()
    flagged = sum(1 for a in agents if state.coaching_profile(raw, a, cfg)["findings"]["focus"])
    team = d[d.settled].north_star.mean()
    ui.kpis([
        {"label": "Team north star", "value": ui.pct(team), "note": "settled tickets, whole period"},
        {"label": "Agent spread", "value": f"{t['north star'].min():.0%} – {t['north star'].max():.0%}",
         "note": "lowest to highest agent"},
        {"label": "Load balance", "value": f"{ratio:.2f}×", "note": f"{load.idxmax()} ÷ {load.idxmin()} · {pd.Period(lm).strftime('%b')}"},
        {"label": "Agents with a clear gap", "value": flagged, "note": f"of {len(t)} agents"},
    ])

    left, right = st.columns([3, 2], gap="large")
    with left:
        ui.section("North star by agent", "Dashed line is the team average.")
        ns = t["north star"].rename("north_star").reset_index().sort_values("north_star")
        ui.hbar_chart(ns, "assigned_agent", "north_star", "North star", "Bar chart of north star by agent.",
                      ref=("Team average", team))
        ui.data_alternative(ns.assign(north_star=ns.north_star.map(ui.pct)))
    with right:
        ui.section("Main point per agent", "Computed from the data. Open the 1:1 prep for the evidence.")
        for agent in t.sort_values("north star").index:
            h = heads[agent]
            prof = state.coaching_profile(raw, agent, cfg)
            has_gap = bool(prof["findings"]["focus"])
            with st.container(border=True):
                left_c, right_c = st.columns([5, 3], vertical_alignment="center")
                left_c.markdown(f"**{agent}**")
                left_c.caption(h["focus"] + (f" · Strength: {h['strength']}" if h["strength"] != "No clear standout" else ""))
                right_c.button("1:1 prep", key=f"to_oo_{agent}", icon=":material/forum:", width="stretch",
                               type="primary" if has_gap else "secondary", on_click=_open_one_on_one, args=(agent,))

    ui.section("All agents")
    ui.dataframe(ui.as_pct(t.reset_index(), ["north star", "escalation rate", "reopen rate"]),
                 hide_index=True, width="stretch",
                 column_order=["assigned_agent", "north star", "coaching note", "tickets", f"tickets in {lm}", "open now",
                               "escalation rate", "avoidable per 100", "reopen rate", "how-to escalations", "CSAT"],
                 column_config={
        "assigned_agent": st.column_config.TextColumn("Agent", pinned=True),
        "tickets": st.column_config.NumberColumn("Tickets"),
        f"tickets in {lm}": st.column_config.NumberColumn(f"Tickets ({lm_label})"),
        "open now": st.column_config.NumberColumn("Open now", format="%d"),
        "north star": st.column_config.ProgressColumn("North star", min_value=0, max_value=100, format=ui.PCT),
        "escalation rate": st.column_config.NumberColumn("Escalation rate", format=ui.PCT),
        "avoidable per 100": st.column_config.NumberColumn("Avoidable / 100", format="%.1f"),
        "reopen rate": st.column_config.NumberColumn("Reopen rate", format=ui.PCT),
        "how-to escalations": st.column_config.NumberColumn("How-to escalations", format="%d"),
        "CSAT": st.column_config.NumberColumn("CSAT", format="%.2f"),
        "coaching note": st.column_config.TextColumn("Main point to discuss", width="large"),
    })
    ui.section("Return reasons by agent", "Count of escalations engineering returned, by reason.")
    rr = pd.crosstab(d.assigned_agent, d.return_reason).reindex(columns=[r for r in ui.T.RETURN_REASON_ORDER
                                                                          if r in d.return_reason.unique()])
    ui.dataframe(rr.rename_axis("Agent").reset_index(), hide_index=True, width="stretch")
    escalation_quality(c)


VIEWS = ["Team overview", "1:1 prep"]


def _open_one_on_one(agent: str) -> None:
    st.session_state.oo_agent_pending = agent
    st.session_state.coaching_tabs = VIEWS[1]


def agent_coaching():
    """One menu item, two tabs. Only the open tab is built, so the page stays fast."""
    from views import oneonone
    tabs = st.tabs(VIEWS, key="coaching_tabs", on_change="rerun")
    with tabs[0]:
        if tabs[0].open:
            _coaching_overview()
    with tabs[1]:
        if tabs[1].open:
            oneonone.agent_one_on_one()


def escalation_quality(c) -> None:
    """Per agent: escalations sent without all the basic checks, or without a detailed note. Counts only escalations
    saved since tracking started (the first saved escalation), so older tickets are never counted as failures."""
    log = store.escalation_log(store.read(), E.load(io.BytesIO(state.raw_data())))
    ui.section("Escalation quality by agent",
               "Escalations sent from My desk with the checks done and a note. Older tickets have neither field and are not counted.")
    if log.empty:
        ui.empty_state("Tracking starts when the first escalation is sent from My desk",
                       "Until then there is nothing to count. Older escalations are never counted as failures.")
        return
    start = log.when.min()
    st.caption(f"Tracking started {start:%d %b %Y, %H:%M}. A detailed note is at least {store.MIN_NOTE_CHARS} characters.")
    log["no_checks"] = log.checks_done < log.checks_total
    log["no_note"] = log.note.str.len() < store.MIN_NOTE_CHARS
    g = log.groupby("agent").agg(escalations=("ticket_id", "size"), no_checks=("no_checks", "sum"), no_note=("no_note", "sum"))
    t = g.reindex(sorted(c.d.assigned_agent.unique()), fill_value=0).astype(int).reset_index().rename(columns={"index": "agent"})
    t["no_checks_rate"] = (t.no_checks / t.escalations.where(t.escalations > 0)).fillna(0)
    t["no_note_rate"] = (t.no_note / t.escalations.where(t.escalations > 0)).fillna(0)
    ui.dataframe(t, hide_index=True, width="stretch", column_config={
        "agent": st.column_config.TextColumn("Agent", pinned=True),
        "escalations": st.column_config.NumberColumn("Escalations tracked"),
        "no_checks": st.column_config.NumberColumn("Without all basic checks"),
        "no_checks_rate": st.column_config.NumberColumn("Share", format="percent"),
        "no_note": st.column_config.NumberColumn("Without a detailed note"),
        "no_note_rate": st.column_config.NumberColumn("Share ", format="percent")})
