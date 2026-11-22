"""Engineering lead: returns, known-issue registry, root causes."""
import pandas as pd
import streamlit as st

import engine as E
import state
import store
import tokens as T
import ui
from views import escalations


def _bounce_card(c, e) -> dict:
    t = c.targets["Bounce rate (2+ handoffs)"]
    card = {"label": "Bounced 2+ times", "value": ui.pct(e.bounced.mean()), "note": "of escalations"}
    if t["value"] is not None:
        card.update(delta=f"target ≤ {ui.pct(t['value'])}", tone="good" if e.bounced.mean() <= t["value"] else "bad")
    return card


def returns():
    c = state.context()
    d, att = c.d, c.att
    e = d[d.esc]
    actions = ui.page_header("Engineering", "Returns from engineering",
                             "Why escalations come back to L1. Every return should carry one of these reason codes. "
                             "Open escalations, engineering lag and the limit are on the Escalations page.")
    actions.download_button("Export escalations", e.drop(columns=["after_go_live"]).to_csv(index=False).encode(),
                            "escalations.csv", "text/csv", icon=":material/download:", on_click="ignore")
    ui.kpis([
        {"label": "Escalations", "value": f"{len(e):,}", "note": f"{d.esc.mean():.0%} of all tickets"},
        {"label": "Avoidable", "value": ui.pct(e.avoidable.mean()), "note": f"{int(e.avoidable.sum())} of {len(e)} escalations"},
        _bounce_card(c, e),
    ])
    state.ticket_cards([{"label": "Returned to L1", "ids": att[att["Returned by eng, waiting on L1"]].ticket_id.tolist(),
                         "note": "open, waiting on L1"}], key="ret_cards")

    ui.section("Return reasons by week", "Escalations engineering sent back, by reason code.")
    order = [r for r in T.RETURN_REASON_ORDER if r in set(e.return_reason.dropna())]
    wk = e.dropna(subset=["return_reason"]).groupby(["week", "return_reason"]).size().rename("n").reset_index()
    if wk.empty:
        ui.empty_state("No returns", "No escalation in this data was returned by engineering.")
    else:
        ui.stacked_bar_chart(wk, "week", "return_reason", "n", order,
                             "Stacked bar chart of returned escalations per week by reason.", y_title="Returned escalations")
        ui.data_alternative(wk.pivot(index="week", columns="return_reason", values="n").fillna(0).astype(int).reset_index())

    ui.section("Still returning after go-live",
               f"Avoidable escalations created on or after {c.go_live:%d %b %Y} (change the date on the Before / after page).")
    after = e[e.after_go_live & e.avoidable]
    if not d.after_go_live.any():
        ui.empty_state("No tickets after go-live yet.",
                       "Set the go-live date inside the data range, or load a newer export.", compact=True)
    else:
        state.ticket_table(after, ["ticket_id", "created_at", "category", "description", "assigned_agent",
                                   "return_reason", "eng_handoffs", "status"], key="ret_after", height=300)

    ui.section("Return reasons by category")
    ct = pd.crosstab(e.category, e.return_reason).reindex(columns=order, fill_value=0)
    ct["Total returned"] = ct.sum(axis=1)
    ct["Escalations"] = e.groupby("category").size()
    ui.dataframe(ct.sort_values("Total returned", ascending=False).rename_axis("Category").reset_index(),
                 hide_index=True, width="stretch")


REG_COLS = ["template", "category", "status", "eng_ticket", "duplicates", "last_seen", "workaround / client reply"]


def _registry_search_and_form(c, reg: pd.DataFrame) -> None:
    """Search the registry by title, category or reply, and add a known issue by hand."""
    q = st.text_input("Search known issues", key="reg_search", placeholder="Title, category or keyword",
                      icon=":material/search:")
    if q.strip():
        s = q.strip().lower()
        hit = reg[reg[["template", "category", "workaround / client reply", "eng_ticket"]].fillna("").astype(str)
                  .apply(lambda col: col.str.lower().str.contains(s, regex=False)).any(axis=1)]
        st.caption(f"{len(hit)} of {len(reg)} known issues match “{q.strip()}”.")
        if hit.empty:
            ui.empty_state("No known issue matches", "Try a shorter keyword, or add it below.", compact=True)
        else:
            ui.dataframe(hit[REG_COLS], hide_index=True, width="stretch")
    with st.expander("Add a known issue", icon=":material/add:"):
        with st.form("new_known_issue", clear_on_submit=True, border=False):
            title = st.text_input("Issue *", placeholder="What clients see, in one line")
            a, b = st.columns(2)
            cat = a.selectbox("Category *", sorted(set(E.CHECKLISTS) | set(c.d.category.dropna())))
            eng = b.text_input("Engineering ticket", placeholder="ENG-1234, if there is one")
            reply = st.text_area("Workaround / client reply", placeholder="What the agent should tell the client")
            if st.form_submit_button("Add known issue", type="primary", icon=":material/add:"):
                if not title.strip():
                    st.error("Add the issue first.", icon=":material/error:")
                else:
                    row = {"template": title.strip(), "category": cat, "status": "Known - open", "eng_ticket": eng.strip(),
                           "duplicates": 0, "last_seen": pd.NaT, "workaround / client reply": reply.strip()}
                    st.session_state.registry = pd.concat([reg, pd.DataFrame([row])], ignore_index=True)
                    store.save_registry(st.session_state.registry)
                    st.session_state.pop("reg_editor", None)
                    state.flash("Known issue added", ":material/check_circle:")
                    st.rerun()


def registry():
    c = state.context()
    actions = ui.page_header("Engineering", "Known-issue registry",
                             "Issues engineering has confirmed and is working on. L1 agents see matching entries in "
                             "the Escalate tab on My desk and link the ticket instead of escalating it again.")
    reg = st.session_state.registry
    actions.download_button("Export registry", reg.to_csv(index=False).encode(), "known_issues.csv", "text/csv",
                            icon=":material/download:", on_click="ignore")
    with actions.popover("Reset", icon=":material/restart_alt:"):
        st.write("Replace the list with the entries seeded from the data? Your edits will be lost.")
        if st.button("Reset registry", type="primary"):
            st.session_state.registry = E.seed_registry(c.d, c.as_of, c.cfg)
            store.save_registry(None)
            st.session_state.pop("reg_editor", None)  # drop pending edits so they are not re-applied to the new list
            state.flash("Registry reset to seeded entries", ":material/restart_alt:")
            st.rerun()

    open_n = int(reg.status.eq("Known - open").sum())
    ui.kpis([{"label": "Open known issues", "value": open_n, "note": "shown to L1 on My desk"},
             {"label": "Fixed and closed", "value": int(reg.status.eq("Fixed - closed").sum()), "note": "hidden from My desk"},
             {"label": "Duplicates explained", "value": int(reg.duplicates.fillna(0).sum()), "note": f"last {c.cfg.registry_days} days"}])
    st.caption(f"Seeded from issues engineering marked 'Duplicate of known issue' in the last {c.cfg.registry_days} days. Matching on issue "
               "type alone also hits real bugs (see Back-tests), so keep entries specific and close them when the fix "
               "ships. Edits are saved on the server for the data in use.")
    _registry_search_and_form(c, reg)
    ui.section("All known issues", "Edit in place, then save.")
    with st.form("registry_form", border=False):
        edited = st.data_editor(
            reg[REG_COLS].reset_index(drop=True), num_rows="dynamic", hide_index=True, width="stretch", key="reg_editor",
            column_config={
                "template": st.column_config.TextColumn("Issue", required=True, width="large"),
                "category": st.column_config.SelectboxColumn(
                    "Category", options=sorted(set(E.CHECKLISTS) | set(c.d.category.dropna())), required=True),
                "status": st.column_config.SelectboxColumn("Status", options=["Known - open", "Fixed - closed"],
                                                           required=True, width="medium"),
                "eng_ticket": st.column_config.TextColumn("Eng ticket", width="small"),
                "duplicates": st.column_config.NumberColumn("Duplicates", disabled=True, width="small"),
                "last_seen": st.column_config.DatetimeColumn("Last seen", disabled=True, format="DD MMM YYYY"),
                "workaround / client reply": st.column_config.TextColumn("Workaround / client reply", width="large"),
            })
        saved = st.form_submit_button("Save changes", type="primary", icon=":material/save:")
    if saved:
        bad = edited[edited.template.fillna("").str.strip().eq("") | edited.category.isna() | edited.status.isna()]
        if len(bad):
            st.error(f"{len(bad)} row(s) need an issue, category and status before saving.", icon=":material/error:")
        else:
            # clear pending edits (they would re-apply to the saved list) and rerun so the cards above update
            st.session_state.registry = edited.reset_index(drop=True)
            store.save_registry(st.session_state.registry)
            st.session_state.pop("reg_editor", None)
            state.flash(f"Registry saved · {int(edited.status.eq('Known - open').sum())} open issues",
                        ":material/check_circle:")
            st.rerun()


def root_causes():
    c = state.context()
    d = c.d
    g = d.groupby("template")
    t = pd.DataFrame({
        "category": g.category.first(), "tickets": g.size(), "escalations": g.esc.sum(),
        "avoidable": g.avoidable.sum(), "median_hours": g.ttr_h.median(), "ticket_hours": g.ttr_h.sum(),
        "reopen_rate": g.reopened.mean(), "clients": g.client_id.nunique(),
    })
    t["hours_share"] = t.ticket_hours / d.ttr_h.sum()
    t = t.sort_values("ticket_hours", ascending=False).rename_axis("issue").reset_index()
    actions = ui.page_header("Engineering", "Root causes / feature gaps",
                             "Recurring issues ranked by the support time they consume. Fixing the top of this list "
                             "removes tickets instead of handling them faster.")
    actions.download_button("Export", t.to_csv(index=False).encode(), "root_causes.csv", "text/csv",
                            icon=":material/download:", on_click="ignore")
    top = t.head(10)
    t_eng, t_prod, t_ops = st.tabs(["Engineering: recurring issues", "Product: feature requests",
                                    "Operations: cab delays and no-shows"])
    with t_eng:
        ui.kpis([
            {"label": "Distinct issues", "value": len(t), "note": "after grouping similar descriptions"},
            {"label": "Top 10 · tickets", "value": ui.pct(top.tickets.sum() / len(d), 0), "note": "of all tickets"},
            {"label": "Top 10 · hours", "value": ui.pct(top.hours_share.sum(), 0), "note": "of resolution hours"},
            {"label": "Top 10 · escalations", "value": ui.pct(top.escalations.sum() / max(d.esc.sum(), 1), 0),
             "note": "of escalations"},
        ])
        ui.section("Top 10 by share of resolution hours", "Fix these first: they remove the most support time.")
        ui.hbar_chart(top[["issue", "hours_share"]], "issue", "hours_share", "Share of all resolution hours",
                      "Bar chart of the ten issues that use the most resolution hours.", fmt=".1%")
        ui.data_alternative(top[["issue", "tickets", "hours_share"]].assign(hours_share=top.hours_share.map(ui.pct)))
        ui.section("All issues")
        ui.dataframe(ui.as_pct(t, ["reopen_rate", "hours_share"]), hide_index=True, width="stretch", column_config={
            "issue": st.column_config.TextColumn("Issue", width="large", pinned=True),
            "category": st.column_config.TextColumn("Category"),
            "tickets": st.column_config.NumberColumn("Tickets"),
            "escalations": st.column_config.NumberColumn("Escalations"),
            "avoidable": st.column_config.NumberColumn("Avoidable"),
            "median_hours": st.column_config.NumberColumn("Median hours", format="%.0f"),
            "ticket_hours": st.column_config.NumberColumn("Ticket-hours", format="%.0f"),
            "reopen_rate": st.column_config.NumberColumn("Reopen rate", format=ui.PCT),
            "clients": st.column_config.NumberColumn("Clients"),
            # max share is NaN when no ticket in the export has closed yet; fall back to a 0-100 bar
            "hours_share": st.column_config.ProgressColumn("Share of hours", min_value=0, format=ui.PCT,
                                                           max_value=float(t.hours_share.max() * 100)
                                                           if t.hours_share.max() > 0 else 100.0),
        })
    with t_prod:
        escalations.feature_requests(c)
    with t_ops:
        escalations.cab_delays(c)
