"""1:1 coaching profiles, computed from the loaded tickets (no numbers are typed in).

For one agent this compares the agent with the OTHER agents (peers), tests whether each gap is bigger than
chance would give, and turns the clear gaps into plain-language findings with the evidence and the tickets to
look at together. Every number shown comes from `metric()` / the review tables, and test_coaching.py recomputes
them independently.

How gaps are judged
- Rates (escalation, reopen, ...): two-proportion z-test, agent vs pooled peers.
- Hours and CSAT: Mann-Whitney U test (normal approximation, ties corrected).
- "Clear gap" = |z| >= 2.58 (about 1 in 100 by chance); "Worth a look" = |z| >= 1.96 (about 1 in 20).
  A gap must also be big enough to matter (see PRACTICAL). With 16 comparisons per agent a few "worth a look"
  results will be chance, so they are labelled as conversation starters, not verdicts.
- Anything with fewer than MIN_N tickets on either side is reported as "not enough data".
"""
import contextlib
from dataclasses import dataclass
from math import erf, sqrt

import numpy as np
import pandas as pd

# Method settings: statistical conventions, listed on the Methodology page. None of them is a measured value.
MIN_N = 20             # fewest tickets on each side before a comparison is made
MIN_CAT_N = 10         # fewest tickets for a ticket-type breakdown
MIN_AGENTS_RANK = 4    # fewest agents before "best on the team" is stated
Z_CLEAR, Z_NOTABLE = 2.58, 1.96   # two-sided 1-in-100 and 1-in-20 chance levels
WATCH_Z = 1.0          # gaps at least this many standard errors are listed as "small differences"
METHOD = {"MIN_N": MIN_N, "MIN_CAT_N": MIN_CAT_N, "MIN_AGENTS_RANK": MIN_AGENTS_RANK, "Z_CLEAR": Z_CLEAR,
          "Z_NOTABLE": Z_NOTABLE, "WATCH_Z": WATCH_Z}
RETURN_REASONS = ["Config", "Missing info", "Duplicate", "How-to", "Not reproducible"]


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    kind: str            # "rate" | "hours" | "score"
    better: str | None   # "low" | "high" | None (neutral)
    group: str           # findings are limited to one per group so they don't repeat each other
    unit: str = "pct"    # display: "pct" | "per100" | "hours" | "score"
    practical: float = 0.03   # smallest gap that matters (fraction for rates, ratio for hours, points for score)


SPECS = [
    Spec("esc_rate", "Escalation rate", "rate", None, "escalation"),
    Spec("avoid_per100", "Avoidable escalations per 100 tickets", "rate", "low", "escalation", "per100"),
    Spec("avoid_share", "Escalations that came back as avoidable", "rate", "low", "escalation", practical=0.05),
    Spec("bounce_rate", "Escalations that bounced 2+ times", "rate", "low", "bounce", practical=0.05),
    Spec("reopen_rate", "Tickets reopened by the client", "rate", "low", "reopen"),
    Spec("reopen_l1", "Reopened, tickets not escalated", "rate", "low", "reopen"),
    Spec("north_star", "Closed on time and not reopened", "rate", "high", "outcome", practical=0.05),
    Spec("quick_close", "Not escalated, first closed unusually fast", "rate", None, "closure", practical=0.05),
    Spec("r_config", "Config returns per 100 tickets", "rate", "low", "reasons", "per100"),
    Spec("r_missing", "Missing-info returns per 100 tickets", "rate", "low", "reasons", "per100"),
    Spec("r_duplicate", "Duplicate escalations per 100 tickets", "rate", "low", "reasons", "per100"),
    Spec("r_howto", "How-to escalations per 100 tickets", "rate", "low", "reasons", "per100"),
    Spec("r_notrepro", "Not-reproducible returns per 100 tickets", "rate", "low", "reasons", "per100"),
    Spec("l1_hours", "Hours to close, not escalated (median)", "hours", "low", "speed_l1", "hours", practical=0.15),
    Spec("eng_hours", "Hours to close, escalated (median)", "hours", "low", "speed_eng", "hours", practical=0.15),
    Spec("frt", "First response, hours (median)", "hours", "low", "frt", "hours", practical=0.25),
    Spec("csat", "CSAT (1–5)", "score", "high", "csat", "score", practical=0.3),
]
SPEC = {s.key: s for s in SPECS}
REASON_KEY = {"Config": "r_config", "Missing info": "r_missing", "Duplicate": "r_duplicate", "How-to": "r_howto",
              "Not reproducible": "r_notrepro"}


# ---------------------------------------------------------------- statistics

def two_prop_z(x1: float, n1: int, x2: float, n2: int) -> float:
    """z for p1 - p2 with a pooled variance. 0 when it cannot be computed."""
    if n1 == 0 or n2 == 0:
        return 0.0
    p = (x1 + x2) / (n1 + n2)
    se = sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return 0.0 if se == 0 else (x1 / n1 - x2 / n2) / se


def mwu_z(a, b) -> float:
    """Mann-Whitney U as a z score (positive = a tends to be larger), with a tie correction."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return 0.0
    ranks = pd.Series(np.concatenate([a, b])).rank().to_numpy()
    u = ranks[:n1].sum() - n1 * (n1 + 1) / 2
    n = n1 + n2
    _, counts = np.unique(np.concatenate([a, b]), return_counts=True)
    tie = (counts ** 3 - counts).sum() / (n * (n - 1))
    var = n1 * n2 / 12 * ((n + 1) - tie)
    return 0.0 if var <= 0 else (u - n1 * n2 / 2) / sqrt(var)


def p_from_z(z: float) -> float:
    return 1 - erf(abs(z) / sqrt(2))


# ---------------------------------------------------------------- metrics

_SHARED: dict | None = None


@contextlib.contextmanager
def shared(d: pd.DataFrame):
    """While open, the agent-independent pieces (a metric's population, every agent's value) are computed once for all agents
    instead of once per agent. Use it when building the profiles of every agent from the same tickets."""
    global _SHARED
    _SHARED = {"d": id(d)}
    try:
        yield
    finally:
        _SHARED = None


def _once(fn):
    def wrapper(d, key, *args):
        if _SHARED is None or _SHARED["d"] != id(d):
            return fn(d, key, *args)
        k = (fn.__name__, key, args)
        if k not in _SHARED:
            _SHARED[k] = fn(d, key, *args)
        return _SHARED[k]
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@_once
def _pop(d: pd.DataFrame, key: str) -> pd.DataFrame:
    """The tickets a metric is measured on."""
    if key in ("esc_rate", "avoid_per100") or key.startswith("r_"):
        return d
    if key in ("avoid_share", "bounce_rate"):
        return d[d.esc]
    if key in ("reopen_rate", "north_star"):
        return d[d.settled]
    if key == "reopen_l1":
        return d[d.settled & ~d.esc]
    if key == "quick_close":
        return d[d.settled & ~d.esc & d.ttf_h.notna()]
    if key == "l1_hours":
        return d[~d.esc & d.ttr_h.notna()]
    if key == "eng_hours":
        return d[d.esc & d.ttr_h.notna()]
    if key == "frt":
        return d[d.frt_h.notna()]
    if key == "csat":
        return d[d.csat_score.notna()]
    raise KeyError(key)


def _values(pop: pd.DataFrame, key: str) -> pd.Series:
    """One value per ticket in pop (0/1 for rates, number for hours/score)."""
    if key == "esc_rate":
        return pop.esc.astype(float)
    if key in ("avoid_per100", "avoid_share"):
        return pop.avoidable.astype(float)
    if key == "bounce_rate":
        return pop.bounced.astype(float)
    if key in ("reopen_rate", "reopen_l1"):
        return pop.reopened.astype(float)
    if key == "north_star":
        return pop.north_star.astype(float)
    if key == "quick_close":
        return pop.quick_close.astype(float)
    if key.startswith("r_"):
        reason = {v: k for k, v in REASON_KEY.items()}[key]
        return (pop.return_reason == reason).astype(float)
    if key in ("l1_hours", "eng_hours"):
        return pop.ttr_h
    if key == "frt":
        return pop.frt_h
    if key == "csat":
        return pop.csat_score
    raise KeyError(key)


@_once
def _pop_values(d: pd.DataFrame, key: str) -> pd.Series:
    return _values(_pop(d, key), key)


def _summary(vals: pd.Series, spec: Spec) -> float:
    if len(vals) == 0:
        return float("nan")
    return float(vals.median()) if spec.kind == "hours" else float(vals.mean())


def metric(d: pd.DataFrame, key: str, agent: str) -> dict:
    """Agent vs peers (all other agents pooled) for one metric."""
    spec = SPEC[key]
    pop = _pop(d, key)
    allv = _pop_values(d, key)                      # one value per ticket; split by agent on the values, not on the whole table
    mine = (pop.assigned_agent == agent).to_numpy()
    va, vp = allv[mine], allv[~mine]
    out = {"key": key, "label": spec.label, "unit": spec.unit, "better": spec.better, "group": spec.group,
           "n_agent": len(va), "n_peers": len(vp), "agent": _summary(va, spec), "peers": _summary(vp, spec),
           "team": _summary(allv, spec)}
    out["peer_agents"] = int(d.assigned_agent.nunique() - 1)
    out["x_agent"] = int(va.sum()) if spec.kind == "rate" else None
    if len(va) < MIN_N or len(vp) < MIN_N:
        return {**out, "z": 0.0, "level": "insufficient", "direction": "", "verdict": "Not enough data"}
    z = two_prop_z(va.sum(), len(va), vp.sum(), len(vp)) if spec.kind == "rate" else mwu_z(va, vp)
    gap = out["agent"] - out["peers"]
    big = (abs(gap) >= spec.practical) if spec.kind != "hours" else \
        (abs(gap) >= spec.practical * out["peers"] and abs(gap) >= 1.0)
    level = "typical"
    if big and abs(z) >= Z_CLEAR:
        level = "clear"
    elif big and abs(z) >= Z_NOTABLE:
        level = "notable"
    if spec.better is None:
        direction = "higher" if gap > 0 else "lower"
    else:
        worse = (gap > 0) if spec.better == "low" else (gap < 0)
        direction = "worse" if worse else "better"
    verdict = {"clear": "Clear gap", "notable": "Worth a look", "typical": "In line with peers"}[level]
    return {**out, "z": float(z), "level": level, "direction": direction if level != "typical" else "", "verdict": verdict}


def fmt(spec_or_key, v: float) -> str:
    spec = SPEC[spec_or_key] if isinstance(spec_or_key, str) else spec_or_key
    if pd.isna(v):
        return "–"
    return {"pct": f"{v:.1%}", "per100": f"{v * 100:.1f}", "hours": f"{v:.1f}h", "score": f"{v:.2f}"}[spec.unit]


@_once
def team_values(d: pd.DataFrame, key: str) -> pd.Series:
    """Value of one metric for every agent (used for ranks and pairing)."""
    spec = SPEC[key]
    pop = _pop(d, key)
    return pop.groupby("assigned_agent").apply(lambda g: _summary(_values(g, key), spec), include_groups=False)


def rank_of(d: pd.DataFrame, key: str, agent: str) -> tuple:
    """(rank, of) where 1 is best, using only agents with enough tickets."""
    spec = SPEC[key]
    pop = _pop(d, key)
    counts = pop.groupby("assigned_agent").size()
    vals = team_values(d, key)[counts[counts >= MIN_N].index]
    if agent not in vals.index or spec.better is None:
        return None, len(vals)
    order = vals.rank(ascending=(spec.better == "low"), method="min")
    return int(order[agent]), len(vals)


def deadlines(d: pd.DataFrame) -> tuple:
    """(L1 hours, engineering hours) the data was scored with, read from the tickets themselves."""
    l1 = d[~d.esc].deadline_h
    eng = d[d.esc].deadline_h
    return (int(l1.iloc[0]) if len(l1) else None, int(eng.iloc[0]) if len(eng) else None)


def escalates_clearly_less(d: pd.DataFrame, agent: str) -> bool:
    m = metric(d, "esc_rate", agent)
    return m["level"] in ("clear", "notable") and m["direction"] == "lower"


# ---------------------------------------------------------------- categories, mix, months

def category_table(d: pd.DataFrame, agent: str) -> pd.DataFrame:
    rows = []
    for cat, g in d.groupby("category"):
        a, p = g[g.assigned_agent == agent], g[g.assigned_agent != agent]
        if len(a) < MIN_CAT_N or len(p) < MIN_N:
            continue
        sa, sp = a[a.settled], p[p.settled]
        rows.append({"category": cat, "tickets": len(a), "escalated": int(a.esc.sum()),
                     "esc_rate": a.esc.mean(), "peer_esc_rate": p.esc.mean(),
                     "esc_z": two_prop_z(a.esc.sum(), len(a), p.esc.sum(), len(p)),
                     "settled": len(sa), "reopened": int(sa.reopened.sum()),
                     "reopen_rate": sa.reopened.mean() if len(sa) else np.nan,
                     "peer_reopen_rate": sp.reopened.mean() if len(sp) else np.nan,
                     "reopen_z": two_prop_z(sa.reopened.sum(), len(sa), sp.reopened.sum(), len(sp))
                     if len(sa) >= MIN_CAT_N and len(sp) >= MIN_N else 0.0})
    return pd.DataFrame(rows, columns=["category", "tickets", "escalated", "esc_rate", "peer_esc_rate", "esc_z", "settled",
                                       "reopened", "reopen_rate", "peer_reopen_rate", "reopen_z"])


def mix_check(d: pd.DataFrame, agent: str) -> dict:
    """What peers' own rates would give on this agent's mix of categories (is it just harder tickets?)."""
    a, p = d[d.assigned_agent == agent], d[d.assigned_agent != agent]
    pr = p.groupby("category").esc.mean()
    counts = a.groupby("category").size()
    exp_esc = float((counts * pr.reindex(counts.index).fillna(p.esc.mean())).sum())
    sa, sp = a[a.settled], p[p.settled]
    rr = sp.groupby("category").reopened.mean()
    sc = sa.groupby("category").size()
    exp_ro = float((sc * rr.reindex(sc.index).fillna(sp.reopened.mean())).sum())
    return {"escalated": int(a.esc.sum()), "expected_escalated": exp_esc, "tickets": len(a),
            "reopened": int(sa.reopened.sum()), "expected_reopened": exp_ro, "settled": len(sa)}


def monthly(d: pd.DataFrame, agent: str) -> pd.DataFrame:
    a = d[d.assigned_agent == agent]
    rows = []
    for m, g in a.groupby("month"):
        s = g[g.settled]
        rows.append({"month": m, "tickets": len(g), "escalated %": g.esc.mean(), "avoidable per 100": g.avoidable.mean() * 100,
                     "reopened %": s.reopened.mean() if len(s) >= MIN_CAT_N else np.nan, "CSAT": g.csat_score.mean()})
    return pd.DataFrame(rows)


def pair_partner(d: pd.DataFrame, agent: str) -> str | None:
    """A peer to learn from: lowest avoidable escalations among agents who do not simply escalate clearly less
    (a low number caused by escalating less is not good practice to copy)."""
    av = team_values(d, "avoid_per100")
    counts = _pop(d, "avoid_per100").groupby("assigned_agent").size()
    cand = [a for a in av.index if a != agent and counts[a] >= MIN_N and not escalates_clearly_less(d, a)]
    return None if not cand else str(av[cand].idxmin())


# ---------------------------------------------------------------- review lists

def review_lists(d: pd.DataFrame, att: pd.DataFrame, agent: str, limit: int = 8) -> dict:
    a = d[d.assigned_agent == agent]
    gap = (a.final_closed_at - a.first_closed_at).dt.total_seconds() / 3600
    reopened = a[a.settled & a.reopened].assign(hours_to_reopen_close=gap)
    reopened = reopened.sort_values(["reopen_count", "created_at"], ascending=[False, False])
    avoid = a[a.avoidable].sort_values(["eng_handoffs", "created_at"], ascending=[False, False])
    slow = a[~a.esc & (a.ttr_h > a.deadline_h)].sort_values("ttr_h", ascending=False)
    open_now = att[att.assigned_agent == agent]
    return {"reopened": reopened, "avoidable": avoid, "slow_l1": slow, "open_now": open_now, "limit": limit}


# ---------------------------------------------------------------- findings

def _vs(m: dict) -> str:
    return f"{fmt(m['key'], m['agent'])} vs {fmt(m['key'], m['peers'])} for the other {m['peer_agents']} agents"


def _esc_line(m: dict) -> str:
    return (f"Escalated {fmt('esc_rate', m['agent'])} of tickets, against {fmt('esc_rate', m['peers'])} for the other "
            f"{m['peer_agents']} agents ({_n(m)}).")


def _n(m: dict) -> str:
    return f"{m['n_agent']:,} tickets"


def _finding(kind, group, headline, evidence, action, questions, level, keys):
    return {"kind": kind, "group": group, "headline": headline, "evidence": evidence, "action": action,
            "questions": questions, "level": level, "keys": keys}


def build_findings(d: pd.DataFrame, agent: str, metrics: dict, cats: pd.DataFrame, mix: dict) -> dict:
    focus, strengths, used = [], [], set()
    M = metrics
    partner = pair_partner(d, agent)
    l1_h, eng_h = deadlines(d)
    quick_h = float(d.quick_close_h.iloc[0]) if "quick_close_h" in d and len(d) else float("nan")

    # --- composite: escalates a lot and many come back
    e, av, avs = M["esc_rate"], M["avoid_per100"], M["avoid_share"]
    if e["level"] in ("clear", "notable") and e["direction"] == "higher" and \
            (av["direction"] == "worse" and av["level"] != "typical" or avs["direction"] == "worse" and avs["level"] != "typical"):
        heavy = cats[cats.esc_z >= Z_NOTABLE].sort_values("escalated", ascending=False)
        where = "; ".join(f"{int(r.escalated)} of {int(r.tickets)} {r.category} tickets escalated "
                          f"(other agents: {r.peer_esc_rate:.0%})" for r in heavy.head(2).itertuples())
        reasons = d[(d.assigned_agent == agent) & d.avoidable].return_reason.value_counts()
        rs = ", ".join(f"{n} {r.lower()}" for r, n in reasons.items())
        ev = [_esc_line(e),
              f"Avoidable escalations per 100 tickets: {_vs(av)}.",
              f"Of the {mix['escalated']} escalations, {int(d[(d.assigned_agent == agent) & d.avoidable].shape[0])} came back "
              f"as avoidable ({rs})."]
        if where:
            ev.append(where[0].upper() + where[1:] + ".")
        ev.append(f"Same mix of ticket types, other agents' own rates would give about {mix['expected_escalated']:.0f} "
                  f"escalations; the agent made {mix['escalated']}.")
        act = ("Use the Escalate tab on My desk for every escalation, and check the known issues it shows first. "
               "Answer how-to questions from the admin guide instead of escalating them.")
        if partner:
            act += f" Shadow {partner} for a week; {partner} has {fmt('avoid_per100', team_values(d, 'avoid_per100')[partner])} " \
                   f"avoidable escalations per 100 tickets with a normal escalation rate."
        focus.append(_finding("focus", "escalation", "Escalates far more than peers, and many come back", ev, act,
                              ["Walk me through the last ticket you escalated that came back. What did you check first?",
                               "Which ticket types do you feel unsure about? Is anything unclear in how we route them?",
                               "Is there a rule or habit telling you to escalate these?"], e["level"],
                              ["esc_rate", "avoid_per100", "avoid_share"]))
        used |= {"escalation", "reasons"}

    # --- composite: closes fast but tickets come back
    r1, ql, l1 = M["reopen_l1"], M["quick_close"], M["l1_hours"]
    if r1["level"] in ("clear", "notable") and r1["direction"] == "worse" and \
            (ql["direction"] == "higher" and ql["level"] != "typical" or l1["direction"] == "better" and l1["level"] != "typical"):
        worst = cats[cats.reopen_z >= Z_NOTABLE].assign(gap=lambda x: x.reopen_rate - x.peer_reopen_rate) \
            .sort_values("gap", ascending=False)
        wtxt = "; ".join(f"{r.category} {r.reopen_rate:.0%} vs {r.peer_reopen_rate:.0%}" for r in worst.head(4).itertuples())
        low_esc = cats[(cats.esc_z <= -Z_NOTABLE)].sort_values("esc_z")
        ltxt = "; ".join(f"{r.category} {r.esc_rate:.0%} vs {r.peer_esc_rate:.0%}" for r in low_esc.head(3).itertuples())
        ev = [f"Tickets not escalated that the client reopened: {_vs(r1)} ({r1['x_agent']} of {r1['n_agent']}).",
              f"Not escalated and first closed within {quick_h:.1f}h (the fastest quarter of first closes across the team): {_vs(ql)}.",
              f"Median hours to close those tickets: {_vs(l1)}."]
        if wtxt:
            ev.append(f"Reopened, by ticket type (agent vs others): {wtxt}.")
        if ltxt:
            ev.append(f"Escalated less than others, by ticket type: {ltxt}.")
        ev.append(f"Reopened tickets in this data: {mix['reopened']} (about {mix['expected_reopened']:.0f} would be expected "
                  f"at other agents' rates for the same ticket types).")
        act = ("Before closing roster, tracking, OTP, cab-delay and report tickets, confirm with the client that the problem "
               "is fixed. If the same symptom returns, escalate. Review the reopened tickets below together.")
        focus.append(_finding("focus", "reopen", "Closes quickly, but the fixes do not hold", ev, act,
                              ["For the reopened tickets below, what did you do to confirm it was fixed?",
                               "When do you decide a ticket needs engineering? What would make you escalate sooner?",
                               "Is the volume manageable, or is speed the only way to keep up?"], r1["level"],
                              ["reopen_l1", "quick_close", "l1_hours"]))
        used |= {"reopen", "closure", "speed_l1"}

    # --- escalates more than peers, yet the escalations are mostly genuine
    if "escalation" not in used and e["level"] in ("clear", "notable") and e["direction"] == "higher":
        mine = d[(d.assigned_agent == agent) & d.avoidable].return_reason.value_counts()
        top = ", ".join(f"{n} {r.lower()}" for r, n in mine.head(2).items()) or "none"
        focus.append(_finding(
            "focus", "escalation", "Escalates more than peers, mostly for real problems",
            [_esc_line(e),
             f"Share of escalations that came back as avoidable: {_vs(avs)}.",
             f"Most common avoidable returns: {top}.",
             f"Same mix of ticket types, other agents' own rates would give about {mix['expected_escalated']:.0f} escalations; "
             f"the agent made {mix['escalated']}."],
            "Look for tickets that engineering could have been spared by one more check (usually config settings). "
            "Pick three escalations from the list below and ask what else could have been tried at L1.",
            ["Which of these needed engineering, and which could you have solved with one more check?",
             "Do you have the access or knowledge to check client settings yourself?"], e["level"], ["esc_rate"]))
        used.add("escalation")

    # --- generic findings
    texts = {
        "avoid_per100": ("Escalations come back more often than peers", "Complete the checklist on My desk before each escalation.",
                         ["What do you check before escalating?"], "Few escalations are sent back", "Ask them to share their pre-escalation checks."),
        "bounce_rate": ("Escalations bounce between L1 and engineering more", f"Make sure each packet is complete; chase engineering at {eng_h} hours.",
                        ["Where do your escalations get stuck?"], "Escalations rarely bounce", "Ask what they put in a packet that others skip."),
        "reopen_rate": ("Clients reopen more of this agent's tickets", "Confirm the fix with the client before closing.",
                        ["How do you confirm a fix before closing?"], "Fixes hold: few tickets are reopened", "Ask them to share how they close tickets."),
        "north_star": ("Fewer tickets closed on time and not reopened", "Pick the one cause below that applies and agree one change.",
                       ["What gets in the way of closing on time?"], "More tickets closed on time and not reopened", "Recognise it; ask what they do differently."),
        "reasons": ("A specific kind of return keeps happening", "Use the matching check: config settings, a complete info packet, the registry, or the help guide.",
                    ["What would help you avoid this return?"], "Few returns of one type", "Ask how they handle this type."),
        "speed_l1": ("Tickets handled without engineering take longer", f"Aim to resolve within {l1_h} hours; look at where time goes.",
                     ["Where does the time go on your slower tickets?"], "Quick on tickets handled without engineering", "Check quality (reopens) before praising speed."),
        "speed_eng": ("Escalated tickets take longer to close", f"Chase engineering at {eng_h} hours and keep the client updated.",
                      ["How do you follow up with engineering?"], "Escalated tickets close faster", "Ask how they work with engineering."),
        "frt": ("Slower first response", "Reply in the first hour and set expectations.", ["What delays your first reply?"],
                "Fast first response", ""),
        "csat": ("Clients rate their tickets lower", "Read the lowest-rated tickets together.", ["What do clients say?"],
                 "Clients rate their tickets higher", ""),
    }
    escalates_less = e["level"] in ("clear", "notable") and e["direction"] == "lower"
    # a low "avoidable" or "returns" number that comes from escalating less is not a strength
    cands = [m for m in metrics.values() if m["level"] in ("clear", "notable") and m["better"]
             and not (escalates_less and m["direction"] == "better" and m["group"] in ("escalation", "reasons", "bounce"))]
    cands.sort(key=lambda m: (m["level"] != "clear", -abs(m["z"])))
    for m in cands:
        g = m["group"]
        if g in used or g in ("closure",):
            continue
        key = "reasons" if g == "reasons" else m["key"] if m["key"] in texts else g
        if key not in texts:
            continue
        head_w, act_w, q_w, head_b, act_b = texts[key]
        if m["direction"] == "worse":
            what = f" ({m['label'].lower()})" if g == "reasons" else ""
            focus.append(_finding("focus", g, head_w + what, [f"{m['label']}: {_vs(m)} ({_n(m)})."], act_w, q_w, m["level"], [m["key"]]))
        else:
            strengths.append(_finding("strength", g, head_b + (f" ({m['label'].lower()})" if g == "reasons" else ""),
                                      [f"{m['label']}: {_vs(m)} ({_n(m)})."], act_b, [], m["level"], [m["key"]]))
        used.add(g)
        if len(focus) + len(strengths) >= 8:
            break

    # --- strengths that are best on the team but within normal variation
    for key, text in (("north_star", "Best on-time, no-reopen rate on the team"), ("reopen_rate", "Lowest reopen rate on the team"),
                      ("bounce_rate", "Fewest bounced escalations on the team"), ("eng_hours", "Fastest escalated tickets on the team"),
                      ("csat", "Highest CSAT on the team"), ("avoid_share", "Lowest share of avoidable escalations on the team")):
        rank, of = rank_of(d, key, agent)
        m = M[key]
        if escalates_less and SPEC[key].group in ("escalation", "reasons", "bounce"):
            continue
        if rank == 1 and of >= MIN_AGENTS_RANK and m["level"] != "insufficient" and not any(key in s["keys"] for s in strengths) \
                and SPEC[key].group not in {s["group"] for s in strengths}:
            note = "" if m["level"] in ("clear", "notable") else " The gap to peers is within normal variation."
            strengths.append(_finding("strength", SPEC[key].group, text,
                                      [f"{m['label']}: {_vs(m)} (best of {of} agents).{note}"], "", [], m["level"], [key]))

    # gaps too small to prove: listed so the conversation can still touch them, clearly labelled
    watch = []
    for m in metrics.values():
        if m["level"] != "typical" or not m["better"]:
            continue
        gap = m["agent"] - m["peers"]
        if (gap > 0 if m["better"] == "low" else gap < 0) and abs(m["z"]) >= WATCH_Z:
            watch.append(m)
    watch = sorted(watch, key=lambda m: -abs(m["z"]))[:3]
    strengths = sorted(strengths, key=lambda s: (s["level"] != "clear", s["level"] != "notable"))[:3]
    return {"focus": focus[:4], "strengths": strengths, "watch": watch}


# ---------------------------------------------------------------- profile

def workload_context(d: pd.DataFrame, agent: str) -> list:
    """Plain facts about volume, so a 1:1 can ask whether the load is manageable."""
    per_agent = d.groupby("assigned_agent").size()
    n, avg = int(per_agent[agent]), float(per_agent.mean())
    out = [f"Handled {n:,} tickets, {n / avg:.2f}× the team average of {avg:,.0f} per agent."]
    months = sorted(d.month.unique())
    if len(months) >= 2:
        first, last = months[0], months[-1]
        mc = d.groupby(["assigned_agent", "month"]).size().unstack(fill_value=0)
        a1, a2 = int(mc.loc[agent, first]), int(mc.loc[agent, last])
        t1, t2 = float(mc[first].mean()), float(mc[last].mean())
        if a1 and t1:
            out.append(f"Monthly tickets went from {a1} ({pd.Period(first).strftime('%b %Y')}) to {a2} "
                   f"({pd.Period(last).strftime('%b %Y')}), {a2 / a1 - 1:+.0%}; "
                       f"the team average per agent went {t2 / t1 - 1:+.0%}.")
    return out


def profile(d: pd.DataFrame, att: pd.DataFrame, agent: str) -> dict:
    """Everything the 1:1 page and export need for one agent."""
    metrics = {s.key: metric(d, s.key, agent) for s in SPECS}
    cats = category_table(d, agent)
    mix = mix_check(d, agent)
    findings = build_findings(d, agent, metrics, cats, mix)
    a = d[d.assigned_agent == agent]
    rated = a.csat_score.notna().sum()
    return {
        "agent": agent, "tickets": len(a), "open": int(a.is_open.sum()),
        "period": (d.created_at.min(), d.created_at.max()), "settled_n": int(a.settled.sum()),
        "metrics": metrics, "categories": cats, "mix": mix, "monthly": monthly(d, agent),
        "review": review_lists(d, att, agent), "findings": findings,
        "reasons": a[a.esc].return_reason.value_counts().reindex(RETURN_REASONS).fillna(0).astype(int),
        "reasons_per_agent": (d[d.esc & d.return_reason.notna()].groupby("return_reason").size().reindex(RETURN_REASONS).fillna(0)
                              / d.assigned_agent.nunique()),
        "csat_coverage": rated / len(a) if len(a) else np.nan, "partner": pair_partner(d, agent),
        "context": workload_context(d, agent),
        "peers": int(d.assigned_agent.nunique() - 1),
    }


def headline_of(p: dict) -> dict:
    f, s = p["findings"]["focus"], p["findings"]["strengths"]
    return {"focus": f[0]["headline"] if f else "No gap stands out against peers",
            "strength": s[0]["headline"] if s else "No clear standout"}


# ---------------------------------------------------------------- export

def to_markdown(p: dict, agreements: dict | None = None) -> str:
    m = p["metrics"]
    lines = [f"# 1:1 prep: {p['agent']}",
             f"Data {p['period'][0]:%d %b %Y} to {p['period'][1]:%d %b %Y} · {p['tickets']:,} tickets · {p['open']} open now · "
             f"compared with the other {p['peers']} agents", ""]
    lines += ["## Start with what is going well"]
    lines += [f"- **{s['headline']}**: " + " ".join(s["evidence"]) for s in p["findings"]["strengths"]] or ["- No clear standout."]
    lines += ["", "## To discuss"]
    if not p["findings"]["focus"]:
        lines.append("- Nothing clearly different from peers.")
    for i, f in enumerate(p["findings"]["focus"], 1):
        lines += [f"### {i}. {f['headline']} ({'clear gap' if f['level'] == 'clear' else 'worth a look'})"]
        lines += [f"- {e}" for e in f["evidence"]]
        lines += [f"- **Suggested action:** {f['action']}"] + [f"- *Ask:* {q}" for q in f["questions"]] + [""]
    lines += ["## Numbers vs the other agents", "", "| Measure | This agent | Other agents | Tickets | Verdict |", "|---|---|---|---|---|"]
    for k in SPEC:
        x = m[k]
        v = x["verdict"] + (f" ({x['direction']})" if x["direction"] else "")
        lines.append(f"| {x['label']} | {fmt(k, x['agent'])} | {fmt(k, x['peers'])} | {x['n_agent']:,} | {v} |")
    mx = p["mix"]
    lines += ["", f"Same ticket mix, other agents' rates: expected about {mx['expected_escalated']:.0f} escalations "
              f"(actual {mx['escalated']}) and {mx['expected_reopened']:.0f} reopens (actual {mx['reopened']}).", ""]
    rv = p["review"]
    for title, df, cols in (("Reopened tickets to review", rv["reopened"], ["ticket_id", "category", "description", "reopen_count"]),
                            ("Avoidable escalations to review", rv["avoidable"], ["ticket_id", "return_reason", "description", "eng_handoffs"]),
                            ("Slow tickets handled without engineering", rv["slow_l1"], ["ticket_id", "description", "ttr_h"])):
        lines += [f"## {title}"]
        lines += [" · ".join(str(r[c]) if c != "ttr_h" else f"{r[c]:.0f}h" for c in cols) for _, r in df.head(rv["limit"]).iterrows()] \
            or ["None."]
        lines.append("")
    ag = agreements or {}
    lines += ["## Agreed in the 1:1", f"- Action: {ag.get('action', '')}", f"- By: {ag.get('by', '')}",
              f"- Support needed: {ag.get('support', '')}", f"- Next review: {ag.get('review', '')}", "",
              "## Read this carefully",
              f"- Gaps are tested against chance; with {len(SPECS)} measures a few 'worth a look' results can be luck.",
              f"- CSAT is given on {p['csat_coverage']:.0%} of this agent's tickets.",
              "- The data shows what happens, not why. Ask before concluding."]
    return "\n".join(lines)
