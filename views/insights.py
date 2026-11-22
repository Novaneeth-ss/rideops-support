"""Shared insight pages: before/after go-live, back-tests, methodology. Every figure is computed from the loaded data."""
from math import sqrt

import pandas as pd
import streamlit as st

import coaching
import engine as E
import state
import ui


def before_after():
    c = state.context()
    d = c.d
    ui.page_header("Insights", "Before / after go-live",
                   "Compare the same measures before and after the workflow changes went live.")
    gl_key = f"go_live_{c.as_of:%Y%m%d}"       # includes the data date, so a new export rebuilds the picker
    st.date_input("Workflow go-live date", key=gl_key, value=c.go_live.date(),
                  on_change=lambda: st.session_state.update(go_live_value=st.session_state[gl_key]),
                  help="Tickets created on or after this date count as after the workflow changes. Saved for next time.")
    before, after = d[~d.after_go_live], d[d.after_go_live]
    if after.empty:
        ui.empty_state("No tickets after go-live yet",
                       f"All {len(d):,} tickets are before {c.go_live:%d %b %Y}, so they form the baseline. "
                       "Pick an earlier go-live date above, or load a newer export, to compare.")
    sb = E.scorecard(before)
    sa = E.scorecard(after) if len(after) else {k: float("nan") for k in sb}
    better_when_low = {"Avoidable escalations per 100 tickets", "Avoidable share of escalations", "Escalation rate",
                       "Bounce rate (2+ handoffs)", "Avg handoffs per escalation", "Duplicate escalations",
                       "Reopen rate", "Reopen rate, non-escalated", "First response median (h)"}
    rows = []
    for k in sb:
        change = ""
        if k != "Tickets" and pd.notna(sa[k]) and pd.notna(sb[k]) and sa[k] != sb[k]:
            good = (sa[k] < sb[k]) == (k in better_when_low)
            change = ui.status("Better" if good else "Worse", "good" if good else "bad")
        rows.append({"Measure": k, "Before": E.fmt_metric(k, sb[k]), "After": E.fmt_metric(k, sa[k]), "Change": change})
    ui.html_table(pd.DataFrame(rows), numeric=("Before", "After"), raw_html=("Change",),
                  caption="Measures before and after go-live")
    st.caption(f"Settled-only measures (north star, on-time, reopen) need tickets at least {c.settle_days} days old. "
               "Duplicate escalations is a count, so compare it per week, not in total. "
               "'Better' and 'Worse' show direction only: they are not tested for chance.")


def backtests():
    c = state.context()
    ui.page_header("Insights", "Back-tests",
                   "Each flag and rule is checked on tickets it had not seen, so you can see how far to trust it.")
    r, g, sc = state.backtests(state.raw_data(), c.cfg)

    ui.section("Reopen-risk flag")
    if r is None:
        ui.empty_state("Not enough history", "Needs an earlier month to train on and reopens in the latest month.")
    else:
        lift = r["precision"] / r["base_rate"] if r["base_rate"] else float("nan")
        ui.kpis([
            {"label": "AUC on unseen tickets", "value": f"{r['auc']:.2f}", "note": "0.5 = chance, 1.0 = perfect"},
            {"label": "Tickets flagged", "value": r["flagged"], "note": f"of {r['test']} (top {c.cfg.reopen_flag_share:.0%})"},
            {"label": "Precision", "value": ui.pct(r["precision"]), "note": f"vs {ui.pct(r['base_rate'])} overall"},
            {"label": "Recall", "value": ui.pct(r["recall"]), "note": "share of reopens caught"},
        ])
        st.caption(f"Trained on {r['train']} tickets created before {r['split']:%d %b %Y}; tested on the latest settled month. "
                   f"Flagged tickets reopened {ui.pct(r['precision'])} of the time against {ui.pct(r['base_rate'])} overall "
                   f"({lift:.1f}× the normal rate). The app uses it to prompt a closure check, never to block closure.")

    ui.section("Automatic escalation blocking",
               "Replays rules over every past escalation. A useful rule would stop many avoidable escalations and almost no real bugs.")
    ui.dataframe(ui.as_pct(g, ["precision (share avoidable)"]), hide_index=True, width="stretch", column_config={
        "rule": st.column_config.TextColumn("Rule", width="large"),
        "would stop": st.column_config.NumberColumn("Would stop"),
        "duplicates caught": st.column_config.NumberColumn("Duplicates caught"),
        "avoidable caught": st.column_config.NumberColumn("Avoidable caught"),
        "real bugs wrongly stopped ('Fixed')": st.column_config.NumberColumn("Real bugs stopped"),
        "precision (share avoidable)": st.column_config.NumberColumn("Precision", format=ui.PCT),
    })
    base_row = g[g.rule.str.startswith("Baseline")].iloc[0]
    rules = g[~g.rule.str.startswith("Baseline") & (g["would stop"] > 0)]
    if len(rules):
        best = rules.loc[rules["precision (share avoidable)"].idxmax()]
        fixed = int(best["real bugs wrongly stopped ('Fixed')"])
        st.caption(f"The most accurate rule is \"{best.rule}\": {best['precision (share avoidable)']:.1%} of what it would stop was "
                   f"avoidable, against {base_row['precision (share avoidable)']:.1%} when stopping every escalation, and it would have "
                   f"stopped {fixed} escalations that engineering went on to fix. "
                   "The Escalate tab on My desk therefore suggests known issues and checks the packet, but does not block automatically.")

    ui.section("Predicting which escalations come back as avoidable",
               "A score built from past escalations (issue type, agent and other ticket fields), tested on the latest month.")
    if sc is None:
        ui.empty_state("Not enough history", "Needs earlier escalations to train on and both outcomes in the latest month.")
    else:
        ui.kpis([
            {"label": "AUC · issue type", "value": f"{sc['auc_issue_type']:.2f}", "note": "0.5 = chance"},
            {"label": "AUC · agent", "value": f"{sc['auc_agent']:.2f}", "note": "0.5 = chance"},
            {"label": "AUC · all six fields", "value": f"{sc['auc_all_fields']:.2f}", "note": "0.5 = chance"},
            {"label": "Escalations tested", "value": sc["test"], "note": f"{ui.pct(sc['base_rate'])} avoidable"},
        ])
        st.caption(f"Trained on {sc['train']} escalations before {sc['split']:%d %b %Y}. A score close to 0.5 means the history "
                   "does not predict which new escalations come back, so the app does not use a risk score for escalations.")


def _csat_by_speed(d: pd.DataFrame) -> pd.DataFrame:
    s = d[d.settled & d.csat_score.notna() & d.ttr_h.notna()]
    if len(s) < 8:
        return pd.DataFrame()
    band = pd.qcut(s.ttr_h, 4, duplicates="drop")
    g = s.groupby(band, observed=True).csat_score.agg(["mean", "size"]).reset_index()
    g["Hours to close"] = g.ttr_h.apply(lambda i: f"{max(i.left, 0):.0f}–{i.right:.0f}h")
    return g.rename(columns={"mean": "Average CSAT", "size": "Rated tickets"})[["Hours to close", "Average CSAT", "Rated tickets"]]


def methodology():
    c = state.context()
    d, base, cfg = c.d, c.base, c.cfg
    s = d[d.settled & d.csat_score.notna()]
    ui.page_header("Insights", "Methodology",
                   "How every number in this app is defined, where each value comes from, and where the limits are. "
                   "Nothing here is typed in: figures are computed from the loaded tickets or come from the settings below.")
    ns_t = c.targets["North star: on-time, no reopen"]
    ui.section("North star: on-time, no-reopen rate")
    lines = [f"A ticket passes if it closed within **{cfg.l1_hours} hours** (not escalated) or **{cfg.eng_hours} hours** "
             "(escalated) **and** the client never reopened it. Both deadlines are policy settings you can change.",
             f"- Whole period ({d.created_at.min():%d %b} to {d.created_at.max():%d %b}): "
             f"**{ui.pct(base['North star: on-time, no reopen'])}**."]
    if ns_t["value"] is not None:
        lines.append(f"- Target: **{ui.pct(ns_t['value'])}**. {ns_t['rule']}.")
    if s.north_star.any() and (~s.north_star).any():
        lines.append(f"- Rated tickets that pass average CSAT **{s[s.north_star].csat_score.mean():.2f}**; "
                     f"those that fail average **{s[~s.north_star].csat_score.mean():.2f}**.")
    st.markdown("\n".join(lines))
    cs = _csat_by_speed(d)
    if len(cs):
        st.markdown("**CSAT by how long the ticket took** (quarters of rated tickets, fastest to slowest):")
        ui.html_table(cs.assign(**{"Average CSAT": cs["Average CSAT"].round(2)}), numeric=("Average CSAT", "Rated tickets"))
        st.caption(f"CSAT is {cs['Average CSAT'].iloc[0]:.2f} in the fastest quarter and {cs['Average CSAT'].iloc[-1]:.2f} in the "
                   "slowest. Use this to judge whether your deadlines sit where satisfaction starts to fall.")

    ui.section("Reading the numbers")
    gap = (d.final_closed_at - d.first_closed_at).dt.total_seconds() / 86400
    gap = gap[d.reopened & gap.notna()]
    sw = d[d.settled].groupby("week").size()
    p = base["North star: on-time, no reopen"]
    margin = 1.96 * sqrt(p * (1 - p) / sw.mean()) if len(sw) and pd.notna(p) else float("nan")
    hi = E.high_impact_threshold(d, cfg)
    weights = ", ".join(f"{k} +{v}" for k, v in E.FLAG_WEIGHTS.items())
    st.markdown(f"""
- **Settled tickets.** The longest gap between a first and a final close in this data is **{gap.max():.1f} days**
  (over {len(gap)} reopened tickets), so a ticket is scored for reopens once it is **{c.settle_days} days** old.
- **Weekly noise.** Settled weeks average **{sw.mean():.0f}** tickets, so the weekly north star moves by about
  **±{margin * 100:.0f} points** from chance alone. Judge on the {cfg.window_weeks}-week line.
- **Open tickets** is the outcome leadership reports. It falls when time-to-close falls, so it is not a target itself.
- **Avoidable escalation:** engineering's outcome was missing info, config, duplicate, how-to or not reproducible.
- **Attention score** adds these weights (a ranking choice): {weights}.
  High impact means at least **{hi:.0f}** people affected (the top {cfg.high_impact_share:.0%} of tickets that state a number).
- **Targets** are derived from this data (see the Scorecard): drivers use the best agent's level today, guardrails mean no
  worse than the whole period.
""")

    ui.section("Where each value comes from")
    q = float(d.quick_close_h.iloc[0]) if len(d) and "quick_close_h" in d else float("nan")
    rows = [("Deadline, not escalated", f"{cfg.l1_hours} h", "Your setting"),
            ("Deadline, escalated", f"{cfg.eng_hours} h", "Your setting"),
            ("Recent weeks counted as 'now'", f"{cfg.window_weeks}", "Your setting"),
            ("Known-issue lookback", f"{cfg.registry_days} days", "Your setting"),
            ("Share flagged as reopen risk", f"{cfg.reopen_flag_share:.0%}", "Your setting"),
            ("High impact = top share by people affected", f"{cfg.high_impact_share:.0%} (≥ {hi:.0f} people)", "Your setting, threshold from data"),
            ("Days before a ticket is scored for reopens", f"{c.settle_days}", "Derived from data"),
            ("'Closed fast' first-close time", f"{q:.1f} h", "Derived: fastest quarter of first closes"),
            ("Targets", "see Scorecard", "Derived: best agent / whole period")]
    rows += [(f"{k}", f"{v}", "Statistical convention") for k, v in {**coaching.METHOD, **E.METHOD}.items()]
    ui.html_table(pd.DataFrame(rows, columns=["Value", "Current", "Source"]), numeric=("Current",))

    ui.section("Known limits")
    st.markdown(f"""
- No engineering pickup or return timestamps, so engineering queue time cannot be split from bounce time.
- Checklists on My desk are starting points to validate with L1 and engineering.
- Known-issue registry edits are saved on the server for the data in use.
- CSAT is answered on {ui.pct(base['CSAT response rate'], 0)} of tickets.
- 'Better' and 'Worse' on the Before / after page show direction only and are not tested for chance.
""")
