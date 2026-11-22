"""Support lead: Agent 1:1 prep. Everything shown is computed by coaching.py from the loaded tickets."""
from html import escape

import pandas as pd
import streamlit as st

import coaching
import state
import store
import ui

LEVEL_TONE = {"clear": "bad", "notable": "warn"}


def _verdict_html(m: dict) -> str:
    if m["level"] == "insufficient":
        return ui.status("Not enough data", "neutral")
    if m["level"] == "typical":
        return ui.status("In line with peers", "neutral")
    tone = "neutral" if not m["better"] else ("good" if m["direction"] == "better" else "bad")
    return ui.status(f"{m['verdict']} · {m['direction']}", tone)


def _finding_card(f: dict, strength: bool = False) -> None:
    with st.container(border=True):
        tone = "good" if strength else LEVEL_TONE.get(f["level"], "neutral")
        if strength:
            label = {"clear": "Clearly better", "notable": "Better than peers"}.get(f["level"], "Best on the team")
        else:
            label = "Clear gap" if f["level"] == "clear" else "Worth a look"
        st.html(f'<p style="margin:0 0 4px;font-weight:600;font-size:1rem">{escape(f["headline"])} {ui.badge(label, tone)}</p>')
        for e in f["evidence"]:
            st.markdown(f"- {e}")
        if f["action"]:
            st.markdown(f"**{'Keep it going' if strength else 'Suggested action'}:** {f['action']}")
        if f["questions"]:
            st.markdown("**Ask:**\n" + "\n".join(f"- {q}" for q in f["questions"]))


def _kpi(m: dict, key: str, label: str) -> dict:
    x = m[key]
    gap = x["agent"] - x["peers"]
    tone = "neutral" if x["level"] in ("typical", "insufficient") or not x["better"] else \
        ("good" if x["direction"] == "better" else "bad")
    return {"label": label, "value": coaching.fmt(key, x["agent"]), "delta": f"{gap * 100:+.1f} pts" if x["unit"] == "pct" else "",
            "tone": tone, "note": f"others {coaching.fmt(key, x['peers'])}"}


def agent_one_on_one():
    c = state.context()
    d = c.d
    agents = sorted(d.assigned_agent.unique())
    ss = st.session_state
    actions = ui.page_header("Support", "Agent 1:1 prep",
                             "Everything for a 1:1, computed from the loaded tickets: what is going well, what to discuss, "
                             "the evidence, and the tickets to look at together. Each agent is compared with the other agents.")
    if len(agents) < 2:
        ui.empty_state("Needs at least two agents", "Comparing an agent with peers needs more than one agent in the data.")
        return
    pending = ss.pop("oo_agent_pending", None)
    if pending in agents:
        ss.oo_agent = pending
    agent = st.selectbox("Agent", agents, key="oo_agent")
    p = state.coaching_profile(state.raw_data(), agent, c.cfg)
    m, f = p["metrics"], p["findings"]
    fields = ("action", "by", "support", "review")
    if ss.get("oo_loaded") != (store.active_key(), agent):      # first view of this agent: bring back what was agreed
        saved = store.kv_get(f"oo:{agent}", {}, ds=None) or {}
        for k in fields:
            ss[f"oo_{k}_{agent}"] = saved.get(k, "")
        ss.oo_loaded = (store.active_key(), agent)
    ag = {k: ss.get(f"oo_{k}_{agent}", "") for k in fields}
    actions.download_button("Download 1:1 summary", coaching.to_markdown(p, ag).encode(), f"1on1_{agent.replace(' ', '_')}.md",
                            "text/markdown", icon=":material/download:", on_click="ignore")
    st.caption(f"Data {p['period'][0]:%d %b %Y} to {p['period'][1]:%d %b %Y} · compared with the other {p['peers']} agents · "
               f"reopens and on-time results use tickets at least {c.settle_days} days old.")

    ui.kpis([{"label": "Tickets", "value": f"{p['tickets']:,}", "note": f"{p['open']} open now"},
             _kpi(m, "north_star", "Closed on time, no reopen"), _kpi(m, "esc_rate", "Escalation rate"),
             _kpi(m, "reopen_rate", "Reopen rate"), _kpi(m, "l1_hours", "Hours to close, not escalated")])

    ui.section("Start with what is going well")
    if f["strengths"]:
        for s_ in f["strengths"]:
            _finding_card(s_, strength=True)
    else:
        ui.empty_state("No clear standout against peers.", "Open with something specific you saw this month.", compact=True)

    ui.section("To discuss", "Only gaps bigger than chance would give are listed as findings.")
    if f["focus"]:
        for f_ in f["focus"]:
            _finding_card(f_)
    else:
        ui.empty_state("No gap stands out against peers.", "Use the 1:1 to ask how the work is going.", compact=True)
    if f["watch"]:
        st.markdown("**Small differences, within normal variation** (could be chance, mention lightly):")
        for w in f["watch"]:
            st.markdown(f"- {w['label']}: {coaching.fmt(w['key'], w['agent'])} vs {coaching.fmt(w['key'], w['peers'])} for the others")

    ui.section("Context to keep in mind")
    for line in p["context"]:
        st.markdown(f"- {line}")
    mx = p["mix"]
    st.markdown(f"- **Is it just harder tickets?** At the other agents' own rates for the same mix of ticket types, "
                f"about **{mx['expected_escalated']:.0f}** of these {mx['tickets']} tickets would be escalated "
                f"(actual: **{mx['escalated']}**) and about **{mx['expected_reopened']:.0f}** of {mx['settled']} settled tickets "
                f"would be reopened (actual: **{mx['reopened']}**).")

    ui.section("Numbers against the other agents", "Hours are medians; CSAT is a mean; rates are shares of the tickets each measure applies to.")
    rows = [{"Measure": x["label"], "This agent": coaching.fmt(k, x["agent"]), "Other agents": coaching.fmt(k, x["peers"]),
             "Tickets": f"{x['n_agent']:,}", "Verdict": _verdict_html(x)} for k, x in m.items()]
    ui.html_table(pd.DataFrame(rows), numeric=("This agent", "Other agents", "Tickets"), raw_html=("Verdict",),
                  caption=f"{agent} compared with the other agents")

    cats = p["categories"]
    if len(cats):
        ui.section("By ticket type", "Ticket types where the agent has at least 10 tickets.")
        show = cats.assign(Escalated=cats.escalated.astype(str) + " of " + cats.tickets.astype(str)).rename(columns={
            "category": "Ticket type", "esc_rate": "Escalated %", "peer_esc_rate": "Others escalated %",
            "reopen_rate": "Reopened %", "peer_reopen_rate": "Others reopened %"})
        pcts = ["Escalated %", "Others escalated %", "Reopened %", "Others reopened %"]
        ui.dataframe(ui.as_pct(show, pcts)[["Ticket type", "Escalated", *pcts]], hide_index=True, width="stretch",
                     column_config={k: st.column_config.NumberColumn(k, format=ui.PCT) for k in pcts})
    st.markdown("**Return reasons** (escalations engineering sent back), this agent vs the average agent:")
    rr = pd.DataFrame({"This agent": p["reasons"], "Average agent": p["reasons_per_agent"].round(1)})
    ui.dataframe(rr.rename_axis("Reason").reset_index(), hide_index=True, width="stretch")
    mo = p["monthly"]
    if len(mo):
        st.markdown("**Month by month** (small samples, so swings of a few points are normal):")
        ui.dataframe(ui.as_pct(mo, ["escalated %", "reopened %"]), hide_index=True, width="stretch", column_config={
            "escalated %": st.column_config.NumberColumn(format=ui.PCT), "reopened %": st.column_config.NumberColumn(format=ui.PCT),
            "avoidable per 100": st.column_config.NumberColumn(format="%.1f"), "CSAT": st.column_config.NumberColumn(format="%.2f")})

    ui.section("Tickets to review together", "Up to 8 per list. Select a row for details.")
    rv = p["review"]
    t1, t2, t3, t4 = st.tabs([f"Reopened ({len(rv['reopened'])})", f"Avoidable escalations ({len(rv['avoidable'])})",
                              f"Slow, not escalated ({len(rv['slow_l1'])})", f"Open now ({len(rv['open_now'])})"])
    lim = rv["limit"]
    with t1:
        state.ticket_table(rv["reopened"].head(lim), ["ticket_id", "created_at", "category", "description", "reopen_count",
                           "status"], key=f"oo_ro_{agent}", height=300, bulk=False)
    with t2:
        state.ticket_table(rv["avoidable"].head(lim), ["ticket_id", "created_at", "return_reason", "description",
                           "eng_handoffs", "ttr_h"], key=f"oo_av_{agent}", height=300, bulk=False)
    with t3:
        state.ticket_table(rv["slow_l1"].head(lim), ["ticket_id", "created_at", "category", "description", "ttr_h", "priority"],
                           key=f"oo_sl_{agent}", height=300, bulk=False)
    with t4:
        state.ticket_table(rv["open_now"].head(lim * 2), ["ticket_id", "attention_score", "flags", "status", "age_h", "description"],
                           key=f"oo_op_{agent}", height=300, bulk=False)

    ui.section("Agree in the 1:1", "Saved for this agent and included in the downloaded summary.")
    a1, a2 = st.columns(2)
    a1.text_input("One action we agree", key=f"oo_action_{agent}", placeholder="E.g. complete the checklist on every roster ticket")
    a2.text_input("By when", key=f"oo_by_{agent}", placeholder="E.g. end of next week")
    b1, b2 = st.columns(2)
    b1.text_input("Support needed from me", key=f"oo_support_{agent}", placeholder="E.g. shadow session with a peer")
    b2.text_input("Next review", key=f"oo_review_{agent}", placeholder="E.g. date of the next 1:1")

    now_vals = {k: ss.get(f"oo_{k}_{agent}", "") for k in fields}
    if now_vals != (store.kv_get(f"oo:{agent}", None, ds=None) or dict.fromkeys(fields, "")):
        store.kv_set(f"oo:{agent}", now_vals, ds=None)

    with st.expander("How to run the 1:1", icon=":material/forum:"):
        st.markdown("1. Open with something that is going well, with the number.\n"
                    "2. Show one finding with its numbers next to the other agents'. Pick one, not all.\n"
                    "3. Ask before explaining. The data shows what happens, not why.\n"
                    "4. Look at two or three tickets from the lists above together.\n"
                    "5. Agree one action, a date and the support you will give. Write it in the boxes above.")
    with st.expander("How to read these numbers", icon=":material/info:"):
        st.markdown(f"- A gap is only called **Clear** or **Worth a look** if it is larger than chance would usually give "
                    f"(about 1 in {round(1 / coaching.p_from_z(coaching.Z_CLEAR))} and 1 in {round(1 / coaching.p_from_z(coaching.Z_NOTABLE))}) and large enough to matter. There are {len(m)} measures per agent, so a "
                    "few 'Worth a look' results will be luck: treat them as conversation starters.\n"
                    f"- Fewer than {coaching.MIN_N} tickets on either side shows as 'Not enough data'.\n"
                    f"- CSAT is given on {p['csat_coverage']:.0%} of this agent's tickets.\n"
                    "- 'Other agents' means all the other agents' tickets pooled together.\n"
                    "- Causes are not in the data. Ask the agent.")
