"""Account health: clients with repeated bad experiences, and a support report for any client."""
import pandas as pd
import streamlit as st

import engine as E
import state
import store
import ui


def account_table(c) -> pd.DataFrame:
    """One row per at-risk client: tier, bad experiences and tickets in the window."""
    d, cfg = c.d, c.cfg
    w = d[(d.created_at <= c.as_of) & (c.as_of - d.created_at <= pd.Timedelta(days=cfg.at_risk_days))]
    risky = E.at_risk_clients(d, c.as_of, cfg)
    g = w[w.client_name.isin(risky.index)].groupby("client_name")
    t = pd.DataFrame({"tier": g.client_tier.first(), "bad": g.bad_exp.sum().astype(int), "tickets": g.size()})
    t["share_bad"] = t.bad / t.tickets
    t = t.sort_values(["bad", "tickets"], ascending=False).rename_axis("client").reset_index()
    calls = {}
    for e in store.read():                                   # the latest recorded call per client
        if e["type"] == "account.called":
            calls[e["data"]["client"]] = e
    t["last_called"] = t.client.map(lambda c: calls[c]["at"][:10] if c in calls else "Not called yet")
    t["called_by"] = t.client.map(lambda c: calls[c]["by"] if c in calls else "")
    return t


def _contact(client: str) -> None:
    """Record that someone called the client, and take the latest record back."""
    last = store.last_call(store.read(), client)
    if last:
        note = f". {last['data']['note']}" if last["data"]["note"] else ""
        st.success(f"Called on {last['at'][:10]} by {last['by']}{note}", icon=":material/call:")
    else:
        st.warning("Nobody has recorded a call to this client yet.", icon=":material/call:")
    with st.form(f"call_{client}", border=False, clear_on_submit=True):
        note = st.text_input("What was said (optional)", key=f"call_note_{client}")
        if st.form_submit_button("Record that I called", icon=":material/call:"):
            store.append("account.called", state.actor(), {"client": client, "note": note.strip()})
            state.flash(f"Call to {client} recorded", ":material/call:")
            st.rerun()
    if last and state.confirm_button("Undo the last call record", f"call_undo_{client}",
                                     "Take the last call record back? It stays in the history with your name.",
                                     icon=":material/undo:"):
        store.undo(last["id"], state.actor())
        st.rerun()


@ui.popup("Account report")
def account_dialog(client: str) -> None:
    c = state.context()
    d, cfg = c.d, c.cfg
    mine = d[d.client_name.eq(client)]
    if mine.empty:
        ui.empty_state("No tickets", f"No tickets for {client}.")
        return
    tier = mine.client_tier.iloc[0]
    st.markdown(f"### {client}")
    _contact(client)
    st.html((ui.badge("At risk", "bad") if mine.at_risk.iloc[0] else ui.badge("Not at risk", "good")) + " " + ui.badge(tier)
            + " " + ui.badge(f"{int(mine.is_open.sum())} open", "neutral"))
    by_month = mine.groupby("month").agg(tickets=("ticket_id", "size"), median_close_h=("ttr_h", "median"))
    st.markdown("**Tickets by month**")
    ui.dataframe(by_month.reset_index().rename(columns={"month": "Month", "tickets": "Tickets",
                                                       "median_close_h": "Median hours to close"}),
                 hide_index=True, width="stretch", column_config={"Median hours to close": st.column_config.NumberColumn(format="%.0f")})
    opened = mine[mine.is_open].sort_values("age_h", ascending=False)
    if len(opened):
        st.markdown(f"**Open tickets** ({len(opened)})")
        ui.dataframe(opened[["ticket_id", "status", "priority", "age_h", "description", "assigned_agent"]], hide_index=True,
                     width="stretch", column_config=state.TABLE_CONFIG)
    win = mine[c.as_of - mine.created_at <= pd.Timedelta(days=cfg.at_risk_days)]
    bad = win[win.bad_exp]
    if len(bad):
        st.markdown(f"**Bad experiences in the last {cfg.at_risk_days} days** ({len(bad)})")
        ui.dataframe(bad[["ticket_id", "priority", "category", "description", "ttr_h", "reopen_count", "csat_score"]],
                     hide_index=True, width="stretch", column_config=state.TABLE_CONFIG)
    rep = mine.groupby("template").filter(lambda x: len(x) >= cfg.at_risk_min_bad).template.unique()
    if len(rep):
        st.markdown(f"**Problems raised {cfg.at_risk_min_bad} or more times**")
        st.markdown("\n".join(f"- {t}" for t in rep))
    lines = [f"{client}: support report", ""]
    lines += [f"{m}: {int(r.tickets)} tickets, median time to close {ui.hours(r.median_close_h)}" for m, r in by_month.iterrows()]
    lines += [f"Open now: {int(mine.is_open.sum())}", "What we are doing: [fixes shipped, owner and date]"]
    st.markdown("**Monthly support report**")
    st.code("\n".join(lines), language=None, wrap_lines=True)


def account_health():
    c = state.context()
    d, cfg = c.d, c.cfg
    t = account_table(c)
    actions = ui.page_header("Support", "Account health",
                             f"Accounts with {cfg.at_risk_min_bad} or more bad experiences in the last {cfg.at_risk_days} days. "
                             "A bad experience is a ticket that took too long, was reopened, or was rated poorly. Open one for its report.")
    actions.download_button("Export accounts", t.to_csv(index=False).encode(), "at_risk_accounts.csv", "text/csv",
                            icon=":material/download:", on_click="ignore")
    w = d[(d.created_at <= c.as_of) & (c.as_of - d.created_at <= pd.Timedelta(days=cfg.at_risk_days))]
    bad_ids = w[w.bad_exp & w.client_name.isin(t.client)].ticket_id.tolist()
    ui.kpis([{"label": "At-risk accounts", "value": len(t), "note": "need a call from the account manager"},
             {"label": "Not called yet", "value": int(t.last_called.eq("Not called yet").sum()), "note": "no call recorded"},
             {"label": "Enterprise", "value": int(t.tier.eq("Enterprise").sum()), "note": "of the at-risk accounts"}])
    state.ticket_cards([{"label": "Bad experiences", "ids": bad_ids, "note": "tickets at at-risk accounts"}], key="health_cards")

    f1, f2 = st.columns([3, 2], vertical_alignment="bottom")
    any_client = f1.selectbox("Find any client", [""] + sorted(d.client_name.unique()), key="health_any",
                              format_func=lambda x: x or "Type a client name…",
                              help="Opens the report for any client, not only those at risk.")
    tier = f2.segmented_control("Tier", ["All"] + sorted(t.tier.unique()), default="All", key="health_tier")
    if any_client and st.session_state.get("health_any_prev") != any_client:
        st.session_state.health_any_prev = any_client
        account_dialog(any_client)
    elif not any_client:
        st.session_state.health_any_prev = None
    ui.section("At-risk accounts", "Select a row for the account report.")
    shown = t if tier in (None, "All") else t[t.tier.eq(tier)]
    if st.toggle("Only accounts not called yet", key="health_uncalled"):
        shown = shown[shown.last_called.eq("Not called yet")]
    if shown.empty:
        ui.empty_state("No accounts at risk", "No client in this tier has enough bad experiences in this window.")
    else:
        ev = ui.dataframe(shown, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                          key=f"health_tbl_{tier}", column_config={
                              "client": st.column_config.TextColumn("Client", pinned=True), "tier": "Tier",
                              "bad": st.column_config.NumberColumn("Bad experiences"),
                              "tickets": st.column_config.NumberColumn("Tickets in window"),
                              "share_bad": st.column_config.NumberColumn("Share bad", format="percent"),
                              "last_called": st.column_config.TextColumn("Last called"),
                              "called_by": st.column_config.TextColumn("Called by")})
        if ev.selection.rows:
            pick = shown.iloc[ev.selection.rows[0]].client
            if st.session_state.get("health_prev") != pick:
                st.session_state.health_prev = pick
                account_dialog(pick)
        else:
            st.session_state.health_prev = None
