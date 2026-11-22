"""Targets and guardrails, derived from the loaded data. No target value is typed in.

Rules (shown next to each target in the app):
- Driver targets are the BEST value any agent in this data already achieves (with enough tickets), so a target is
  something the team has demonstrated is possible. For "avoidable escalations" an agent who simply escalates clearly
  less than the others is not used as the benchmark: a low number from escalating less is not good practice.
- Guardrails are "no worse than the team's whole-period level".
"""
import numpy as np
import pandas as pd

import coaching as C
import engine as E

# measure key (as in engine.scorecard) -> (kind, direction, coaching metric key or None, rule text)
DRIVERS = {
    "North star: on-time, no reopen": ("min", "north_star"),
    "Avoidable escalations per 100 tickets": ("max", "avoid_per100"),
    "Bounce rate (2+ handoffs)": ("max", "bounce_rate"),
    "Escalated closed on time": ("min", None),
    "Reopen rate": ("max", "reopen_rate"),
}
GUARDRAILS = {
    "CSAT (avg)": "min",
    "Escalations ending 'Fixed'": "min",
    "Reopen rate, non-escalated": "max",
    "First response median (h)": "max",
}


def _agent_values(d: pd.DataFrame, measure: str, key: str | None) -> pd.Series:
    """The measure for every agent that has enough tickets for it."""
    if key:
        vals = C.team_values(d, key)
        counts = C._pop(d, key).groupby("assigned_agent").size()
        return vals[counts[counts >= C.MIN_N].index]
    # escalated closed on time, per agent
    s = d[d.settled & d.esc & d.ttr_h.notna()]
    g = s.groupby("assigned_agent")
    ok = g.apply(lambda x: (x.ttr_h <= x.deadline_h).mean(), include_groups=False)
    return ok[g.size()[g.size() >= C.MIN_N].index]


def targets(d: pd.DataFrame) -> dict:
    """measure -> {value, direction, rule, agent}. value is None when the data cannot support a target."""
    base = E.scorecard(d)
    out = {}
    for measure, (direction, key) in DRIVERS.items():
        vals = _agent_values(d, measure, key)
        if measure.startswith("Avoidable"):
            vals = vals[[a for a in vals.index if not C.escalates_clearly_less(d, a)]]
        if len(vals) < 2:
            out[measure] = {"value": None, "direction": direction, "agent": None,
                            "rule": "Needs at least two agents with enough tickets"}
            continue
        better_high = direction == "min"
        agent = vals.idxmax() if better_high else vals.idxmin()
        rule = f"Best agent today ({agent})"
        if measure.startswith("Avoidable"):
            rule += ", leaving out agents who escalate clearly less than the others"
        scale = 100 if key == "avoid_per100" else 1     # the scorecard shows this one per 100 tickets
        out[measure] = {"value": float(vals[agent]) * scale, "direction": direction, "rule": rule, "agent": str(agent)}
    for measure, direction in GUARDRAILS.items():
        v = base[measure]
        out[measure] = {"value": None if pd.isna(v) else float(v), "direction": direction, "agent": None,
                        "rule": "No worse than the whole-period team level"}
    return out


def met(value, target, direction) -> bool | None:
    if value is None or target is None or pd.isna(value):
        return None
    return value >= target if direction == "min" else value <= target


def nan_safe(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else x
