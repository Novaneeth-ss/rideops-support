"""Head of Operations: scorecard. Targets come from targets.py (derived from the loaded data)."""
import pandas as pd
import streamlit as st

import engine as E
import state
import targets as TG
import ui

NUM = {"Avoidable escalations per 100 tickets", "CSAT (avg)", "First response median (h)"}   # shown as numbers, not %


def _fmt(measure, v):
    return ("–" if pd.isna(v) else f"{v:.1f}") if measure in NUM else ui.pct(v)


def last_settled_weeks(d: pd.DataFrame, n: int) -> pd.DataFrame:
    weeks = sorted(d[d.settled].week.unique())
    return d[d.settled & d.week.isin(weeks[-n:])] if weeks else d.iloc[0:0]


def scorecard():
    c = state.context()
    d, base, cfg = c.d, c.base, c.cfg
    n_w = cfg.window_weeks
    l1_h, eng_h = cfg.l1_hours, cfg.eng_hours
    actions = ui.page_header("Overview", "Scorecard",
                             "Is support getting better? North star, open tickets and the drivers behind them, measured on "
                             f"settled tickets (at least {c.settle_days} days old, the time a reopen takes to show up in this data).")
    w = E.weekly(d, cfg)
    csv = w.reset_index().rename(columns={"week": "week_start"}).to_csv(index=False).encode()
    actions.download_button("Export weekly data", csv, "rideops_weekly.csv", "text/csv",
                            icon=":material/download:", on_click="ignore")

    recent = last_settled_weeks(d, n_w)
    if recent.empty:
        ui.empty_state("No settled weeks yet", f"Tickets must be {c.settle_days}+ days old to score. Load a longer export.")
        return
    now = E.scorecard(recent)
    stock = E.open_stock(d, c.as_of)
    ns_t = c.targets["North star: on-time, no reopen"]
    ns, ns0 = now["North star: on-time, no reopen"], base["North star: on-time, no reopen"]
    av, av0 = now["Avoidable escalations per 100 tickets"], base["Avoidable escalations per 100 tickets"]
    ro, ro0 = now["Reopen rate"], base["Reopen rate"]
    back = n_w * 7
    prev_stock = stock.iloc[-(back + 1)] if len(stock) > back else stock.iloc[0]

    def tone(better):
        return "good" if better else "bad"

    w0, w1 = recent.week.min(), recent.week.max() + pd.Timedelta(days=6)
    st.caption(f"Rates cover the last {n_w} settled weeks ({w0:%d %b} – {w1:%d %b}), compared with the "
               f"{d.created_at.min():%d %b}–{d.created_at.max():%d %b} average. Counts are as of {c.as_of:%d %b %Y}. "
               f"On time = within {l1_h}h (not escalated) or {eng_h}h (escalated); change these under Policy settings.")
    cards = [{"label": "North star", "value": ui.pct(ns), "delta": f"{(ns - ns0) * 100:+.1f} pts",
              "tone": tone(ns >= ns0), "note": f"vs {ui.pct(ns0)} avg"}]
    if ns_t["value"] is not None:
        cards.append({"label": "Target", "value": ui.pct(ns_t["value"]), "delta": f"{(ns_t['value'] - ns) * 100:.1f} pts",
                      "tone": "neutral", "note": f"to go · {ns_t['agent']}'s level"})
    cards += [
        {"label": "Open tickets", "value": int(stock.iloc[-1]), "delta": f"{int(stock.iloc[-1] - prev_stock):+d}",
         "tone": tone(stock.iloc[-1] <= prev_stock), "note": f"vs {n_w} weeks ago"},
        {"label": "Need attention", "value": int((c.att.attention_score >= 3).sum()), "note": f"of {len(c.att)} open tickets"},
        {"label": "Avoidable escalations", "value": f"{av:.1f}", "delta": f"{av - av0:+.1f}",
         "tone": tone(av <= av0), "note": f"per 100 · vs {av0:.1f}"},
        {"label": "Reopen rate", "value": ui.pct(ro), "delta": f"{(ro - ro0) * 100:+.1f} pts",
         "tone": tone(ro <= ro0), "note": f"vs {ui.pct(ro0)} avg"}]
    ui.kpis(cards)

    left, right = st.columns(2, gap="large")
    with left:
        ui.section("North star trend", f"{n_w}-week rolling share of tickets closed on time and not reopened.")
        tr = w.dropna(subset=["north_star_rolling"]).reset_index()[["week", "north_star_rolling"]]
        ref = {f"Period avg {ns0:.1%}": (ns0, "text-muted")}
        if ns_t["value"] is not None:
            ref[f"Target {ns_t['value']:.1%}"] = (ns_t["value"], "success")
        ui.line_chart(tr, "week", "north_star_rolling", f"North star ({n_w}-wk rolling)",
                      f"Line chart of the {n_w}-week rolling north star by week, with the target and period average.", ref=ref)
        ui.data_alternative(tr.assign(north_star_rolling=tr.north_star_rolling.map(ui.pct)))
    with right:
        ui.section("Open tickets", "End-of-day open count. Starts at zero on the export's first day.")
        sdf = stock.rename_axis("date").reset_index()
        ui.line_chart(sdf, "date", "open_tickets", "Open tickets", "Area chart of open tickets at the end of each day.",
                      fmt="d", area=True)
        ui.data_alternative(sdf)

    ui.section("Drivers of the north star", "Each driver by week on settled tickets, with its target. A line that moves the "
               "wrong way pulls the north star down with it.")
    se = d[d.settled & d.esc]
    esc_ok = (se.ttr_h <= se.deadline_h).groupby(se.week).mean()
    drivers = [("Avoidable escalations per 100 tickets", "avoidable_per_100", ".1f", "Avoidable escalations per 100 tickets"),
               ("Bounce rate (2+ handoffs)", "bounce_rate", ".0%", "Escalations bounced 2+ times"),
               ("Escalated closed on time", "esc_on_time", ".0%", f"Escalated tickets closed within {eng_h}h"),
               ("Reopen rate", "reopen_rate", ".0%", "Reopen rate")]
    wk = w.assign(esc_on_time=esc_ok).reset_index()
    for row in range(0, len(drivers), 2):
        for col, (measure, key, fmt, title) in zip(st.columns(2, gap="large"), drivers[row:row + 2]):
            with col:
                st.markdown(f"**{title}**")
                tr = wk.dropna(subset=[key])[["week", key]]
                tgt = c.targets[measure]["value"]
                ref = {f"Target {format(tgt, fmt)}": (tgt, "success")} if tgt is not None else None
                if tr.empty:
                    ui.empty_state("No settled weeks yet", "This driver appears once tickets have settled.", compact=True)
                    continue
                ui.line_chart(tr, "week", key, title, f"Line chart of {title.lower()} by week.", fmt=fmt, ref=ref, height=200)
                ui.data_alternative(tr.assign(**{key: tr[key].map(lambda v, f=fmt: format(v, f))}))
    ui.section("Targets", f"Last {n_w} settled weeks against target. Every target is derived from this data: drivers use the "
               "best agent's level today, guardrails mean no worse than the whole period.")
    labels = {"Escalated closed on time": f"Escalated closed within {eng_h}h"}
    rows = []
    for measure, t in c.targets.items():
        v = now[measure]
        ok = TG.met(None if pd.isna(v) else v, t["value"], t["direction"])
        status = ui.status("On track" if ok else "Off track", "good" if ok else "bad") if ok is not None \
            else ui.status("No target", "neutral")
        kind = "North star" if measure.startswith("North star") else "Driver" if measure in TG.DRIVERS else "Guardrail"
        tgt = "–" if t["value"] is None else ("≥ " if t["direction"] == "min" else "≤ ") + _fmt(measure, t["value"])
        gap = "–"
        if t["value"] is not None and not pd.isna(v):
            diff = v - t["value"]
            gap = f"{diff:+.1f}" if measure in NUM else f"{diff * 100:+.1f} pts"
        rows.append({"Measure": labels.get(measure, measure), "Type": kind, "Period avg": _fmt(measure, base[measure]),
                     f"Last {n_w} weeks": _fmt(measure, v), "Target": tgt, "Gap": gap, "Status": status,
                     "How the target is set": t["rule"]})
    ui.html_table(pd.DataFrame(rows), numeric=("Period avg", f"Last {n_w} weeks", "Target", "Gap"), raw_html=("Status",),
                  caption="Targets and current status")

    st.caption("Gap is the last weeks minus the target: a negative gap on a measure where higher is better, or a positive gap "
               "where lower is better, means still to go. Avoidable escalations and bounces are worked on the Returns page, "
               "open tickets on the Attention queue.")

    with st.expander("Weekly detail", type="compact", icon=":material/table_view:"):
        ui.dataframe(ui.as_pct(w.reset_index(), ["north_star", "north_star_rolling", "reopen_rate", "bounce_rate"]),
                     hide_index=True, width="stretch", column_config={
            "week": st.column_config.DateColumn("Week of", format="DD MMM YYYY"),
            "tickets": st.column_config.NumberColumn("Tickets"),
            "north_star": st.column_config.NumberColumn("North star", format=ui.PCT),
            "north_star_rolling": st.column_config.NumberColumn(f"{n_w}-wk rolling", format=ui.PCT),
            "avoidable_per_100": st.column_config.NumberColumn("Avoidable / 100", format="%.1f"),
            "reopen_rate": st.column_config.NumberColumn("Reopen rate", format=ui.PCT),
            "bounce_rate": st.column_config.NumberColumn("Bounce rate", format=ui.PCT),
            "frt_median_h": st.column_config.NumberColumn("First response (h)", format="%.1f"),
        })
        st.caption("Empty north star cells are weeks still settling.")
