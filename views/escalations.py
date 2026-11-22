"""Engineering: the Escalations page, and the engineering-lag section used on Returns from engineering.

Rules enforced here:
- A ticket escalated a second time cannot be bounced back to support. The return button is disabled and the ticket
  carries the flag "Call required: engineering + agent". store.apply enforces the same rule when a log is replayed.
- "Escalate to engineering head" is offered to the support lead roles. There are no logins, so this is a menu rule,
  not security: anyone can switch role.
"""
import pandas as pd
import streamlit as st

import engine as E
import state
import store
import ui

LEADS = ("Support lead", "All views", "Admin")
ENGINEERS = ("Engineering lead", "All views", "Admin")
CALL_FLAG = "Call required: engineering + agent"


def _role() -> str:
    return st.session_state.get("role_value", "All views")


def _who() -> str:
    return state.actor()


def return_to_l1(t, reason: str) -> bool:
    """Send a ticket back to support. A ticket on its second escalation or later is flagged for a call instead."""
    if t.call_required or t.eng_handoffs >= 2:
        store.append("ticket.call_required", _who(), {"id": t.ticket_id})
        return False
    store.append("ticket.return", _who(), {"id": t.ticket_id, "reason": reason})
    return True


def escalations():
    c = state.context()
    d = c.d
    open_e = d[d.status.eq("Open - with Engineering")].sort_values("created_at")
    ui.page_header("Engineering", "Escalations",
                   "Tickets with engineering now. Return one to L1 with a reason, mark it fixed, or see that it needs a call. "
                   "A ticket escalated a second time cannot be returned.")
    state.ticket_cards([
        {"label": "Open escalations", "ids": open_e.ticket_id.tolist(), "note": "with engineering now"},
        {"label": "Call required", "ids": open_e[open_e.call_required].ticket_id.tolist(),
         "note": f"second escalation or later · {int((open_e.call_required & open_e.call_held_at.notna()).sum())} call(s) recorded"},
        {"label": "Engineering lag", "ids": open_e[open_e.eng_lag].ticket_id.tolist(), "note": "past the engineering limit"},
        {"label": "Verdict, status not updated", "ids": open_e[open_e.eng_outcome.notna()].ticket_id.tolist(),
         "note": "engineering answered, still marked with them"},
    ], key="esc_cards")
    t_open, t_lag, t_time = st.tabs(["Open escalations", "Lag and limit", "Time with engineering"])
    with t_open:
        _open_tab(c, open_e)
    with t_lag:
        lag_section(c)
    with t_time:
        tracking_section(c)


@st.fragment
def _open_tab(c, open_e) -> None:
    """A fragment: picking a row or clicking Details reruns only this tab, not the whole page."""
    if open_e.empty:
        ui.empty_state("No open escalations", "Engineering is clear.")
        return
    att = c.att
    ui.section("Open escalations", "Oldest first. Select a row to act on it below.")
    view = att[att.ticket_id.isin(open_e.ticket_id)].sort_values("age_h", ascending=False)
    state.ticket_table_body(view, ["ticket_id", "eng_ticket_id", "age_h", "eng_handoffs", "eng_outcome", "flags", "category",
                              "description", "client_name", "assigned_agent"], key="esc_tbl", height=340, bulk=False,
                       pick_key="esc_pick")

    ids = open_e.ticket_id.tolist()
    pick = st.session_state.get("esc_pick")
    if pick not in ids:
        pick = ids[0]
    ui.section(f"Act on {pick}")
    if _role() not in ENGINEERS + LEADS:
        st.caption("Switch the role to Engineering lead or All views (or sign in as an administrator) to return or close escalations.")
    t = open_e[open_e.ticket_id.eq(pick)].iloc[0]
    left, right = st.columns([5, 1], vertical_alignment="center")
    left.markdown(f"**{t.client_name}** · {t.description}")
    if right.button("Details", key="esc_details", icon=":material/open_in_new:", width="stretch"):
        state.ticket_dialog(pick)
    can_act = _role() in ENGINEERS
    if t.call_required:
        if pd.notna(t.call_held_at):
            st.success(f"Call held on {t.call_held_at:%d %b %H:%M} with {t.call_held_with}. The ticket still cannot be returned "
                       "to support: mark it fixed once engineering has fixed it.", icon=":material/call:")
        else:
            st.error(f"{CALL_FLAG}. This ticket has been to engineering {int(t.eng_handoffs)} times, so it cannot be returned "
                     "to support. The engineer and the agent talk to each other, agree the cause, and record the call here.",
                     icon=":material/call:")
            if _role() in ENGINEERS + LEADS:
                with st.form("call_form", border=False):
                    who = st.text_input("Who was on the call", placeholder="Engineer and agent, e.g. Sandeep and Priya D")
                    note = st.text_input("What was agreed (optional)")
                    if st.form_submit_button("Record call held", icon=":material/call:"):
                        if not who.strip():
                            st.error("Say who was on the call.", icon=":material/error:")
                        else:
                            store.append("ticket.call_held", _who(), {"id": t.ticket_id, "who": who.strip(), "note": note.strip()})
                            state.flash(f"Call recorded on {t.ticket_id}", ":material/call:")
                            st.rerun()
    a, b = st.columns([3, 1], vertical_alignment="bottom")
    reason = a.selectbox("Return reason", store.RETURN_REASONS, key="esc_reason", disabled=not can_act or bool(t.call_required))
    with b:
        if state.confirm_button("Return to L1", "esc_return", f"Return {t.ticket_id} to L1 as “{reason}”? The agent owns it "
                                "again. You can undo it afterwards.", disabled=not can_act or bool(t.call_required),
                                icon=":material/undo:", help=CALL_FLAG if t.call_required else None, width="stretch"):
            ok = return_to_l1(t, reason)
            state.flash(f"{t.ticket_id} returned to L1" if ok else f"{t.ticket_id}: {CALL_FLAG}",
                        ":material/undo:" if ok else ":material/call:")
            st.rerun()
    if state.confirm_button("Mark fixed", "esc_fixed", f"Mark {t.ticket_id} fixed? It goes back to the agent to confirm with "
                            "the client. You can undo it afterwards.", disabled=not can_act, icon=":material/check_circle:"):
        store.append("ticket.fixed", _who(), {"id": t.ticket_id})
        state.flash(f"{t.ticket_id} marked fixed", ":material/check_circle:")
        st.rerun()
    state.undo_control(t.ticket_id, "esc")


def lag_section(c) -> None:
    """Engineering lag: the limit, the delay card, tracking, the lag list and the escalate-to-head action."""
    d, cfg = c.d, c.cfg
    lag = d[d.eng_lag].sort_values("lag_delay_h", ascending=False)
    sla = float(d.eng_sla_h.iloc[0]) if len(d) else float("nan")
    base = E.eng_sla_baseline(d)
    n_base = int((d.esc & d.ttr_h.notna()).sum())
    ui.section("Engineering lag",
               "A ticket is in engineering lag when it has been with engineering longer than the limit, or a lead marked it.")
    left, right = st.columns([3, 2], gap="large")
    with left:
        total = lag.lag_delay_h.sum()
        state.ticket_cards([{"label": "Delay caused by engineering lag", "ids": lag.ticket_id.tolist(),
                             "note": (f"{total:.0f} h over the limit in total · {total / len(lag):.0f} h on average" if len(lag)
                                      else "no ticket is over the limit"),
                             "columns": ["ticket_id", "status", "eng_ticket_id", "eng_hours", "lag_delay_h", "lag_basis",
                                         "description", "assigned_agent"]}], key="lag_card")
    with right:
        ui.fields([("Limit in use", "–" if pd.isna(sla) else f"{sla:.0f} h" + (" (set by a lead)" if cfg.eng_sla_hours else " (baseline)")),
                   ("Baseline", "No closed escalated ticket yet" if pd.isna(base)
                    else f"{base:.0f} h = slowest quarter's boundary of {n_base} closed escalated tickets")])
        if _role() in LEADS + ENGINEERS:
            with st.form("sla_form", border=False):
                hrs = st.number_input("Engineering limit (hours)", min_value=1, step=1, value=max(1, int(round(sla))) if pd.notna(sla) else 1,
                                      help="One value for the whole app. Lower it as engineering gets faster.")
                if st.form_submit_button("Save limit", icon=":material/save:"):
                    store.append("config.eng_sla", _who(), {"hours": int(hrs)})
                    st.session_state.pop("set_eng_sla_hours", None)
                    state.flash(f"Engineering limit saved: {int(hrs)} h", ":material/save:")
                    st.rerun()
    st.caption("The export has no time into and out of engineering, so for older tickets the measure is age since creation "
               "(a proxy that includes L1 time). Tickets escalated from My desk are timed exactly.")
    if lag.empty:
        ui.empty_state("No ticket is over the limit", "Nothing is in engineering lag right now.", compact=True)
    else:
        state.ticket_table(lag, ["ticket_id", "status", "eng_ticket_id", "eng_hours", "lag_delay_h", "lag_basis", "description",
                                 "assigned_agent"], key="lag_tbl", height=300, bulk=False)
        if _role() in LEADS:
            pick = st.selectbox("Escalate to engineering head", lag.ticket_id.tolist(), key="head_pick")
            note = st.text_input("Note for the engineering head", key="head_note", placeholder="What is blocked, and since when")
            if state.confirm_button("Escalate to engineering head", "head_go", f"Escalate {pick} to the engineering head? "
                                    "This is recorded against your role. You can undo it afterwards.", type="primary",
                                    icon=":material/north:"):
                store.append("ticket.eng_head", _who(), {"id": pick, "note": note.strip()})
                state.flash(f"{pick} escalated to the engineering head", ":material/north:")
                st.rerun()
            heads = lag[lag.eng_head_at.notna()]
            if len(heads):
                st.caption("Already escalated to the head: " + ", ".join(heads.ticket_id))
        else:
            st.caption("Support leads can escalate these to the engineering head. Switch the role to Support lead or All views.")
    open_e = d[d.status.eq("Open - with Engineering") & ~d.eng_lag]
    if _role() in LEADS and len(open_e):
        pick = st.selectbox("Mark a ticket as engineering lag by hand", open_e.ticket_id.tolist(), key="mark_pick")
        if state.confirm_button("Mark as lag", "mark_go", f"Mark {pick} as engineering lag by hand? You can undo it afterwards.",
                                icon=":material/flag:"):
            store.append("ticket.lag_mark", _who(), {"id": pick})
            state.flash(f"{pick} marked as engineering lag", ":material/flag:")
            st.rerun()


def tracking_section(c) -> None:
    d = c.d
    ui.section("Time with engineering", "Recorded from the first escalation sent from My desk. Older tickets are not back-filled.")
    tr = d[d.tracked]
    if tr.empty:
        ui.empty_state("Tracking starts with the first escalation sent from My desk",
                       "Until then there is no measured time with engineering.", compact=True)
    else:
        st.caption(f"Tracking started {tr.eng_entered_at.min():%d %b %Y, %H:%M}.")
        ui.dataframe(tr[["ticket_id", "eng_ticket_id", "eng_entered_at", "eng_left_at", "eng_hours", "status"]]
                     .rename(columns={"ticket_id": "Ticket", "eng_ticket_id": "Eng ticket", "eng_entered_at": "Entered engineering",
                                      "eng_left_at": "Left engineering", "eng_hours": "Hours with engineering", "status": "Status"}),
                     hide_index=True, width="stretch", column_config={
                         "Entered engineering": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm"),
                         "Left engineering": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm"),
                         "Hours with engineering": st.column_config.NumberColumn(format="%.1f")})


def feature_requests(c) -> None:
    """Feature asks found in how-to tickets, counted by ticket and client, with a status Product can set."""
    d = c.d
    ask = d[d.category.str.startswith("How-to") & d.description.str.match(r"^(Can we|Request:|Need option)")]
    ui.section("Feature requests", "Asks found in how-to tickets, grouped by wording. Set a status once Product has decided.")
    if ask.empty:
        ui.empty_state("No feature requests", "No how-to ticket in this data reads as a feature ask.", compact=True)
        return
    months = sorted(d.month.unique())
    g = ask.groupby("template")
    t = pd.DataFrame({"tickets": g.size(), "clients": g.client_id.nunique(),
                      "by_month": g.month.apply(lambda m: " / ".join(str(int((m == x).sum())) for x in months))})
    t = t.sort_values("tickets", ascending=False).rename_axis("request").reset_index()
    saved = store.feature_status(store.read())
    t["status"] = t.request.map(saved).fillna("No decision")
    ui.dataframe(t, hide_index=True, width="stretch", column_config={
        "request": st.column_config.TextColumn("Request", width="large", pinned=True),
        "tickets": st.column_config.NumberColumn("Tickets"), "clients": st.column_config.NumberColumn("Clients"),
        "by_month": st.column_config.TextColumn("By month · " + " / ".join(months)), "status": "Status"})
    with st.form("feature_status_form", border=False):
        a, b = st.columns([3, 1], vertical_alignment="bottom")
        pick = a.selectbox("Request", t.request.tolist())
        status = b.selectbox("Status", ["Under review", "Planned", "Declined", "Shipped"])
        if st.form_submit_button("Save status", icon=":material/save:"):
            store.append("feature.status", _who(), {"key": pick, "status": status})
            state.flash("Feature request status saved", ":material/save:")
            st.rerun()


def cab_delays(c) -> None:
    """Cab delays and no-shows (from the reference app's Patterns page): fleet and vendor problems that support
    can log but Operations owns. Wording variants are merged ("... late for 9 PM shift" and "... for night shift")."""
    d = c.d
    cab = d[d.category.str.startswith("Cab delay")].copy()
    ui.section("Cab delays and no-shows",
               "Fleet and vendor problems. Support can log them; Operations owns the fix. Wording variants are merged.")
    if cab.empty:
        ui.empty_state("No cab-delay tickets", "No ticket in this data has a cab-delay category.", compact=True)
        return
    cab["issue"] = cab.template.str.replace(r" for .* shift| on route N this week", "", regex=True)
    months = sorted(d.month.unique())
    g = cab.groupby("issue")
    t = pd.DataFrame({"category": g.category.first(), "tickets": g.size(), "clients": g.client_id.nunique(),
                      "escalated": g.esc.sum().astype(int),
                      "by_month": g.month.apply(lambda m: " / ".join(str(int((m == x).sum())) for x in months))})
    t = t.sort_values("tickets", ascending=False).reset_index()
    ui.dataframe(t, hide_index=True, width="stretch", column_config={
        "issue": st.column_config.TextColumn("Issue", width="large", pinned=True),
        "category": "Category", "tickets": st.column_config.NumberColumn("Tickets"),
        "clients": st.column_config.NumberColumn("Clients"), "escalated": st.column_config.NumberColumn("Escalated"),
        "by_month": st.column_config.TextColumn("By month · " + " / ".join(months))})
    st.caption("Owner: Operations (fleet and vendors). “Driver marked employee no-show without arriving” may be a "
               "driver-conduct problem. The export has no vendor or driver field, so vendors and drivers cannot be ranked.")
