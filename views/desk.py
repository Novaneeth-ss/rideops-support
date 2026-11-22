"""My desk: one agent's open tickets with the next step, the context and the escalation check. This is the one place
to escalate: it checks known issues first, then records the checks and the note. Replies and closing are drafted here
but not sent or saved: there is no client channel to send through."""
from html import escape

import pandas as pd
import streamlit as st

import engine as E
import state
import store
import tickets
import ui


def _context_lines(c, t) -> list:
    d, cfg = c.d, c.cfg
    others = d[d.ticket_id.ne(t.ticket_id)]
    same = others[others.client_id.eq(t.client_id) & others.template.eq(t.template) & others.created_at.lt(t.created_at)]
    recent = others[others.client_id.eq(t.client_id) & (c.as_of - others.created_at <= pd.Timedelta(days=cfg.at_risk_days))]
    elsewhere = others[others.is_open & others.template.eq(t.template) & others.client_id.ne(t.client_id)]
    out = [f"This client raised this issue {len(same)} time(s) before: " + ", ".join(same.ticket_id.head(5)) if len(same)
           else "First time this client raised this issue.",
           f"{len(recent)} other tickets from this client in the last {cfg.at_risk_days} days"
           + (f"; {int(recent.bad_exp.sum())} were bad experiences." if t.at_risk else "."),
           f"Same issue is open for {len(elsewhere)} other client(s) right now. Possible incident." if len(elsewhere)
           else "Not open for any other client right now."]
    return out


GENERIC = ["Steps to reproduce", "Affected users / trips and time", "Screenshot or error message"]
DEFAULT_REPLY = "This is a known issue and engineering is working on it. We will update you soon."


def _known_issues(t, agent: str) -> bool:
    """Step 1: an open known issue in this category. Linking records it and ends the escalation. True when linked."""
    if t.known_issue:
        st.success(f"Linked to a known issue: {t.known_issue}. No escalation needed.", icon=":material/link:")
        return True
    reg = st.session_state.registry
    hits = reg[reg.category.eq(t.category) & reg.status.eq("Known - open")].reset_index(drop=True)
    st.markdown("**1 · Known issues**")
    if hits.empty:
        st.caption("No open known issue in this category. Continue to the checklist.")
        return False
    st.caption("Link only if the client's symptoms match. Matching on the issue type alone also hits real bugs.")
    for i, h in hits.iterrows():
        eng = h.eng_ticket if pd.notna(h.eng_ticket) and str(h.eng_ticket).strip() else "no engineering ticket yet"
        reply = h["workaround / client reply"]
        reply = reply if pd.notna(reply) and str(reply).strip() else DEFAULT_REPLY
        with st.container(border=True):
            st.markdown(f"**{h.template}**")
            st.caption(eng)
            if state.confirm_button("Link, don't escalate", f"desk_ki_{t.ticket_id}_{i}",
                                    f"Link {t.ticket_id} to “{h.template}”? It will not go to engineering.",
                                    icon=":material/link:"):
                store.append("ticket.known_issue", state.actor(agent), {"id": t.ticket_id, "issue": h.template})
                state.flash(f"{t.ticket_id} linked to a known issue", ":material/link:")
                st.rerun()
            with st.expander("Reply to send to the client"):
                st.code(reply, language=None, wrap_lines=True)
    return False


def _send(t, agent: str, payload: dict) -> None:
    store.append("ticket.escalate", state.actor(agent), {"id": t.ticket_id, **payload})
    state.flash(f"{t.ticket_id} sent to engineering ({payload['checks_done']} of {payload['checks_total']} checks done)",
                ":material/send:")
    st.rerun()


STANDARD = "Standard (built-in)"
DEFAULTS = {
    "reply": "Hi {client} team,\n\nThanks for reporting \"{issue}\". We are looking into it now and will update you as soon "
             "as there is news.\n\nRideOps Support",
    "close": "Hi {client} team,\n\nWe believe \"{issue}\" is fixed. Could you confirm it is working for you? We will keep "
             "the ticket open until you confirm.\n\nRideOps Support",
}


def _macro_box(kind: str, t, agent: str) -> None:
    """Pick the built-in text or one of this person's own templates, see it filled in for this ticket, and save or delete templates."""
    ss = st.session_state
    owner = state.actor(agent)
    mine = store.macros(owner, kind)
    names = [STANDARD] + [m["name"] for m in mine]
    key = f"desk_macro_{kind}"
    pick = ss.pop(f"{key}_pick", None)          # a template saved a moment ago becomes the selected one
    if pick in names:
        ss[key] = pick
    if ss.get(key) not in names:
        ss[key] = STANDARD
    choice = st.selectbox("Template", names, key=key, help=f"Your own templates are saved under {owner}.")
    body = DEFAULTS[kind] if choice == STANDARD else next(m["body"] for m in mine if m["name"] == choice)
    values = {"client": t.client_name, "ticket": t.ticket_id, "issue": t.description, "category": t.category,
              "agent": t.assigned_agent}
    st.code(store.fill_macro(body, values), language=None, wrap_lines=True)
    with st.expander("Save your own template", icon=":material/bookmark_add:"):
        st.caption("Write it once and pick it here next time. Words in curly brackets are filled in for each ticket: "
                   + ", ".join(store.MACRO_PLACEHOLDERS) + ".")
        with st.form(f"desk_macro_form_{kind}", border=False, clear_on_submit=False):
            name = st.text_input("Template name", key=f"{key}_new_name", max_chars=store.MACRO_NAME_MAX,
                                 placeholder="E.g. Roster sync, known issue")
            text = st.text_area("Text", key=f"{key}_new_text", max_chars=store.MACRO_BODY_MAX, height=160,
                                value=DEFAULTS[kind])
            saved = st.form_submit_button("Save template", icon=":material/save:")
        if saved:
            err = store.save_macro(owner, kind, name, text)
            if err:
                st.error(err, icon=":material/error:")
            else:
                ss[f"{key}_pick"] = name.strip()
                state.flash(f"Template “{name.strip()}” saved", ":material/bookmark_added:")
                st.rerun()
    if choice != STANDARD and state.confirm_button("Delete this template", f"{key}_del", f"Delete “{choice}”? "
                                                   "Tickets already sent are not affected.", icon=":material/delete:"):
        store.delete_macro(owner, kind, choice)
        ss.pop(key, None)
        state.flash(f"Template “{choice}” deleted", ":material/delete:")
        st.rerun()


def packet_text(t, items: list, ticked: list, answers: list, note: str) -> str:
    """The case as plain text to paste into the engineering ticket: each check, whether it was done, and the answer given."""
    lines = [f"Ticket: {t.ticket_id} · {t.client_name} · {t.priority}", f"Category: {t.category}", f"Issue: {t.description}", "",
             "Checks:"]
    for item, ok, ans in zip(items, ticked, answers):
        lines.append(f"  [{'x' if ok else ' '}] {item}")
        if ans:
            lines.append(f"      Answer: {ans}")
    return "\n".join(lines + ["", f"Findings: {note.strip() or '(none)'}"])


@st.fragment
def _escalation_tab(c, t, agent: str) -> None:
    """A fragment: ticking a check or typing an answer updates only this tab, and the text to copy follows what is typed."""
    ss = st.session_state
    if t.status != "Open - with L1":
        st.info("This ticket is already with engineering. Follow it on the Escalations page.", icon=":material/send:")
        return
    if _known_issues(t, agent):
        return
    items = E.CHECKLISTS.get(t.category, GENERIC)
    st.markdown("**2 · Checks and answers**")
    st.caption("For each check, write what you found. A check with an answer counts as done; you can also just tick it. "
               "Engineering returns most tickets for missing information. If you send with checks or the note missing, you are "
               "asked to confirm and it is recorded that way.")
    ticked, answers = [], []
    for n, item in enumerate(items):
        with st.container(border=True):
            box = st.checkbox(item, key=f"desk_chk_{t.ticket_id}_{n}")
            ans = st.text_input(f"Answer for: {item}", key=f"desk_ans_{t.ticket_id}_{n}", label_visibility="collapsed",
                                placeholder="What you found (optional)", max_chars=300).strip()
        ticked.append(bool(box or ans))
        answers.append(ans)
    note = st.text_area("What you checked and what you saw", key=f"desk_note_{t.ticket_id}",
                        placeholder="E.g. cutoff in admin is 18:00, roster job ran at 18:05, 3 employees missing")
    st.markdown("**3 · Text to copy**")
    st.caption("Updates as you type. Use the copy icon, then paste it into the engineering ticket or chat. "
               "\"Send to engineering\" below records the escalation in this app.")
    st.code(packet_text(t, items, ticked, answers, note), language=None, wrap_lines=True)
    pkey = f"desk_payload_{t.ticket_id}"
    payload = {"note": note.strip(), "checks_done": int(sum(ticked)), "checks_total": len(items),
               "answers": [{"check": i, "done": ok, "answer": a} for i, ok, a in zip(items, ticked, answers)]}
    if ss.get(pkey) and ss[pkey] != payload:
        ss.pop(pkey)                                          # the agent changed something after pressing Send: ask again
    if st.button("Send to engineering", type="primary", icon=":material/send:", key=f"desk_esc_{t.ticket_id}"):
        if payload["checks_done"] == payload["checks_total"] and len(payload["note"]) >= store.MIN_NOTE_CHARS:
            _send(t, agent, payload)
        ss[pkey] = payload
        ss[f"desk_send_{t.ticket_id}__armed"] = True          # ask before sending an incomplete escalation
    if ss.get(pkey):
        p = ss[pkey]
        gaps = [f"{p['checks_total'] - p['checks_done']} of {p['checks_total']} checks not done"]             if p["checks_done"] < p["checks_total"] else []
        if len(p["note"]) < store.MIN_NOTE_CHARS:
            gaps.append("no detailed note")
        if state.confirm_button("Send anyway", f"desk_send_{t.ticket_id}", f"{', '.join(gaps).capitalize()}. "
                                "It is recorded that way against your name. Send anyway?", icon=":material/send:"):
            _send(t, agent, ss.pop(pkey))
        elif not ss.get(f"desk_send_{t.ticket_id}__armed"):
            ss.pop(pkey, None)


def desk():
    c = state.context()
    d, att, cfg = c.d, c.att, c.cfg
    ss = st.session_state
    agents = sorted(d.assigned_agent.unique())
    pending = ss.pop("desk_pending", None)
    if pending and (d.ticket_id == pending).any():
        ss.desk_agent = d.loc[d.ticket_id == pending, "assigned_agent"].iloc[0]
        ss.desk_pick = pending
    if ss.get("desk_agent") not in agents:
        counts = att.groupby("assigned_agent").size()
        ss.desk_agent = counts.idxmax() if len(counts) else agents[0]
    actions = ui.page_header("Support", "My desk", "Your open tickets with the next step, the context and the checks to run "
                             "before escalating.")
    agent = actions.selectbox("Agent", agents, key="desk_agent", label_visibility="collapsed")
    mine = att[att.assigned_agent.eq(agent)]
    with actions.popover("Shift handover", icon=":material/swap_horiz:"):
        st.caption(f"Built from {agent}'s open tickets. Paste it into the team channel.")
        st.code(tickets.handover(agent, mine), language=None, wrap_lines=True)

    state.ticket_cards([
        {"label": "Open with you", "ids": mine.ticket_id.tolist(), "note": "tickets assigned to you"},
        {"label": "With engineering", "ids": mine[mine.status.eq("Open - with Engineering")].ticket_id.tolist(),
         "note": "waiting on engineering"},
        {"label": "Need attention", "ids": mine[mine.attention_score >= 3].ticket_id.tolist(), "note": "flags add up to a high score"},
    ], key="desk_cards")
    if mine.empty:
        ui.empty_state("Queue clear", "No open tickets for this agent.")
        return

    left, right = st.columns([2, 3], gap="large")
    with left:
        ui.section("My queue", f"{len(mine)} open, most urgent first")
        view = mine[["ticket_id", "priority", "age_h", "description"]]
        ev = ui.dataframe(view, hide_index=True, height=520, width="stretch", on_select="rerun", selection_mode="single-row",
                          key=f"desk_df_{agent}", column_config=state.TABLE_CONFIG)
    rows = [r for r in ev.selection.rows if r < len(view)]
    pick = view.iloc[rows[0]].ticket_id if rows else ss.get("desk_pick")
    if pick not in set(mine.ticket_id):
        # open on a ticket the agent can act on (with L1), not one that is already with engineering
        actionable = mine[mine.status.eq("Open - with L1")]
        pick = (actionable if len(actionable) else mine).ticket_id.iloc[0]
    t = d[d.ticket_id.eq(pick)].iloc[0]
    flags = [f for f in mine.loc[mine.ticket_id.eq(pick), "flags"].iloc[0].split("; ") if f]
    with right:
        st.markdown(f"## {t.ticket_id} · {t.client_name}")
        st.html(ui.badge(t.client_tier, "neutral") + " " + (ui.badge("At-risk account", "bad") if t.at_risk else "") + " "
                + " ".join(ui.badge(E.short_flag(f), "bad" if f.startswith("Call") else "warn", E.FLAG_HELP.get(f, "")) for f in flags))
        st.caption(f"{t.category} · {t.channel} · created {t.created_at:%d %b %Y, %H:%M} · {ui.hours(t.age_h)} old"
                   + (f" · {int(t.affected)} people affected" if pd.notna(t.affected) else ""))
        st.html(f'<p class="rx-lead">{escape(t.description)}</p>')
        sug, why = tickets.suggest_priority(t, d, cfg)
        st.markdown(f"Priority **{t.priority}**" + (f" · suggested **{sug}** ({', '.join(why)})" if sug != t.priority
                                                    else " · matches the rules"))
        moves = tickets.next_moves(t, flags, cfg)
        st.info("**Next step.** " + " ".join(moves[:2]), icon=":material/arrow_forward:")
        st.markdown("**Context**")
        st.markdown("\n".join(f"- {x}" for x in _context_lines(c, t)))
        tab_reply, tab_esc, tab_close = st.tabs(["Draft reply", "Escalate", "Draft close message"])
        with tab_reply:
            st.caption("Draft only: this app does not send messages. Copy it into your email or chat.")
            _macro_box("reply", t, agent)
        with tab_esc:
            _escalation_tab(c, t, agent)
        with tab_close:
            if "Reopen risk: confirm before closing" in flags:
                st.warning("Tickets like this reopen more than most. Confirm the fix with the client before closing.",
                           icon=":material/replay:")
            st.caption("Ask the client to confirm before closing. Closing is not recorded in this app.")
            _macro_box("close", t, agent)
