"""Shared engine: loads tickets, computes the metric tree and attention flags.

Every screen in app.py reads from here so all roles see the same numbers.
"""
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

DATES = ["created_at", "first_response_at", "first_closed_at", "final_closed_at"]
REQUIRED = ["ticket_id", "created_at", "channel", "client_id", "client_name", "client_tier",
            "category", "priority", "description", "assigned_agent", "first_response_at",
            "escalated_to_eng", "eng_ticket_id", "eng_handoffs", "eng_outcome", "status",
            "first_closed_at", "final_closed_at", "reopen_count", "csat_score"]

AVOIDABLE = ["Insufficient info - returned to L1", "Config issue - returned to L1",
             "Duplicate of known issue", "Not a bug - how-to", "Not reproducible"]
RETURN_CODES = {
    "Insufficient info - returned to L1": "Missing info",
    "Config issue - returned to L1": "Config",
    "Duplicate of known issue": "Duplicate",
    "Not a bug - how-to": "How-to",
    "Not reproducible": "Not reproducible",
}



@dataclass(frozen=True)
class Settings:
    """Values that are policy choices, not facts in the data. They are shown and editable in the app
    (Policy settings in the sidebar), and every number that depends on them says so. Everything else is derived from the tickets."""
    l1_hours: int = 24            # on-time line for tickets that are not escalated
    eng_hours: int = 72           # on-time line for escalated tickets
    window_weeks: int = 4         # how many recent settled weeks count as "now"
    registry_days: int = 30       # how far back a "duplicate of known issue" counts when seeding the registry
    reopen_flag_share: float = 0.20   # share of tickets flagged as reopen risk
    high_impact_share: float = 0.25   # "high impact" = the largest this share of tickets by people affected
    at_risk_days: int = 30            # an account is judged on tickets raised in this many days before the export ends
    at_risk_min_bad: int = 3          # bad experiences in that window that make an account "at risk"
    slow_close_hours: int = 72        # a ticket that took longer than this counts as a bad experience
    overload_percent: int = 150       # an agent is overloaded above this % of the team's average open tickets
    eng_sla_hours: int = 0            # time allowed with engineering; 0 = use the baseline computed from the data


# Method conventions (shown on Methodology, not measured values)
QUICK_CLOSE_QUANTILE = 0.25     # "closed fast" = the fastest quarter of first-close times
SMOOTHING = 10                  # pseudo-tickets pulling a small group's rate toward the overall rate
SLA_QUANTILE = 0.75             # engineering-time baseline = the slowest quarter's boundary (median would flag half)
LONG_OPEN_DAYS = 7              # the "Tickets open 7+ days" flag
LOW_CSAT = 2                    # a rating at or below this is a bad experience
METHOD = {"QUICK_CLOSE_QUANTILE": QUICK_CLOSE_QUANTILE, "SMOOTHING": SMOOTHING, "SLA_QUANTILE": SLA_QUANTILE}
BULK_RE = re.compile(r"(\d+)\s+(users|employees|trips)", re.I)

# Checklist v1: hypotheses to validate with L1 + engineering (no escalation notes in the data).
CHECKLISTS = {
    "Roster / booking not syncing": [
        "Client's booking cutoff / roster config checked in admin",
        "Shift date + shift time affected",
        "Number of employees affected and 2-3 employee IDs",
        "Booking/cancellation made by admin or employee, and when",
        "Screenshot of roster vs booking screen",
    ],
    "Live tracking / GPS incorrect": [
        "Trip ID and cab number",
        "Exact time window of the issue (time-stamped)",
        "Driver app version and phone model",
        "Screenshot or screen recording of the map",
        "Who sees it (employee app / admin / security link) and their role",
    ],
    "Report export failing": [
        "Checked known-issue registry for this report",
        "Report name, date range and format",
        "Admin user and role used",
        "Error message or screenshot",
    ],
    "OTP / boarding issue": [
        "Trip ID, employee ID and driver ID",
        "Time of attempt (time-stamped)",
        "Driver app version",
        "Did employee receive OTP (SMS / app)?",
    ],
    "Billing / invoice discrepancy": [
        "Invoice number and billing period",
        "Client's rate card / vendor config checked",
        "Trip IDs that do not match, with client's own records",
    ],
    "Login / access issue": [
        "User ID, role and SSO / password login",
        "Access/role config checked in admin",
        "Number of users affected",
    ],
    "Employee address / geocode change": [
        "Employee IDs and new address",
        "Address updated where (admin / employee app) and when",
        "Pin location screenshot",
    ],
    "Cab delay / no-show complaint": [
        "Trip ID, shift and scheduled vs actual time",
        "Driver ID and GPS trail checked",
    ],
    "Driver / vehicle compliance docs": [
        "Driver / vehicle ID and document type",
        "Upload error or screenshot",
    ],
    "How-to / feature request": [
        "Checked help article / admin guide",
        "If feature request: log in product backlog, not engineering escalation",
    ],
}


def load(src) -> pd.DataFrame:
    """Read the ticket CSV (path or uploaded file) and validate its columns."""
    df = pd.read_csv(src)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(missing)}")
    if df.empty:
        raise ValueError("CSV has no ticket rows")
    for c in DATES:
        # ISO 8601 accepts "2026-07-02 01:27" and "2026-07-02 01:27:00" (exports often add seconds)
        df[c] = pd.to_datetime(df[c], errors="coerce", format="ISO8601")
    bad = int(df.created_at.isna().sum())
    if bad:
        raise ValueError(f"{bad} row(s) have a created_at that is not a date like '2026-07-02 01:27'")
    for c in ("eng_handoffs", "reopen_count", "csat_score"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df[["eng_handoffs", "reopen_count"]] = df[["eng_handoffs", "reopen_count"]].fillna(0)
    # tolerate "yes" / " Yes " from other export tools
    df["escalated_to_eng"] = df.escalated_to_eng.fillna("").astype(str).str.strip().str.capitalize()
    return df


def settle_days(df: pd.DataFrame) -> int:
    """Days after creation by which a reopen would have appeared: the longest gap between a ticket's first and
    final close in this data, rounded up, plus one day. Tickets younger than this are not scored for reopens."""
    gap = (df.final_closed_at - df.first_closed_at).dt.total_seconds() / 86400
    gap = gap[(df.reopen_count.fillna(0) > 0) & gap.notna()]
    return int(np.ceil(gap.max())) + 1 if len(gap) else 1


def eng_sla_baseline(d: pd.DataFrame) -> float:
    """Baseline for time with engineering: the 75th percentile of created-to-close hours of closed escalated tickets.
    A proxy (it includes L1 time) because the export has no time into and out of engineering."""
    x = d[d.esc & d.ttr_h.notna()].ttr_h
    return float(x.quantile(SLA_QUANTILE)) if len(x) else float("nan")


def at_risk_clients(d: pd.DataFrame, as_of: pd.Timestamp, cfg: Settings) -> pd.Series:
    """Bad-experience count per client (tickets raised in the window), for clients at or over the threshold."""
    w = d[(d.created_at <= as_of) & (as_of - d.created_at <= pd.Timedelta(days=cfg.at_risk_days))]
    n = w.bad_exp.groupby(w.client_name).sum()
    return n[n >= cfg.at_risk_min_bad].sort_values(ascending=False)


def enrich(df: pd.DataFrame, as_of: pd.Timestamp, cfg: Settings | None = None, wall_now=None) -> pd.DataFrame:
    cfg = cfg or Settings()
    d = df.copy()
    for c, v in {"eng_entered_at": pd.NaT, "eng_left_at": pd.NaT, "eng_done_h": 0.0, "call_required_ev": False,
                 "lag_marked": False, "tracked": False, "call_held_at": pd.NaT}.items():
        if c not in d:
            d[c] = v
    def hrs(a, b):
        return (d[b] - d[a]).dt.total_seconds() / 3600
    d["esc"] = d.escalated_to_eng.eq("Yes")
    d["reopened"] = d.reopen_count.fillna(0) > 0
    d["is_open"] = d.final_closed_at.isna()
    d["ttr_h"] = hrs("created_at", "final_closed_at")
    d["ttf_h"] = hrs("created_at", "first_closed_at")
    d["frt_h"] = hrs("created_at", "first_response_at")
    d["age_h"] = (as_of - d.created_at).dt.total_seconds() / 3600
    d["template"] = d.description.str.replace(r"\d+", "N", regex=True)
    d["avoidable"] = d.eng_outcome.isin(AVOIDABLE)
    d["return_reason"] = d.eng_outcome.map(RETURN_CODES)
    d["bounced"] = d.eng_handoffs.fillna(0) >= 2
    d["deadline_h"] = np.where(d.esc, cfg.eng_hours, cfg.l1_hours)
    d["on_time"] = d.ttr_h <= d.deadline_h
    d["north_star"] = d.on_time & ~d.reopened            # only meaningful once settled
    d["settled"] = d.created_at <= as_of - pd.Timedelta(days=settle_days(df))
    d["affected"] = d.description.str.extract(BULK_RE)[0].astype(float)
    d["week"] = d.created_at.dt.to_period("W").dt.start_time
    d["month"] = d.created_at.dt.to_period("M").astype(str)
    # "closed fast" = in the fastest quarter of first-close times for tickets not escalated (derived, not a fixed hour count)
    base = d[d.settled & ~d.esc & d.ttf_h.notna()].ttf_h
    quick_h = float(base.quantile(QUICK_CLOSE_QUANTILE)) if len(base) else float("nan")
    d["quick_close_h"] = quick_h
    d["quick_close"] = d.ttf_h <= quick_h
    # accounts and long-open tickets
    d["bad_exp"] = (d.ttr_h > cfg.slow_close_hours) | d.reopened | (d.csat_score <= LOW_CSAT)
    risky = at_risk_clients(d, as_of, cfg)
    d["at_risk"] = d.client_name.isin(risky.index)
    d["long_open"] = d.is_open & (d.age_h > LONG_OPEN_DAYS * 24)
    # engineering: 2nd escalation cannot be bounced; time with engineering and lag against the SLA
    with_eng = d.status.eq("Open - with Engineering")
    d["call_required"] = d.call_required_ev.astype(bool) | (d.esc & with_eng & (d.eng_handoffs >= 2))
    d["eng_sla_h"] = float(cfg.eng_sla_hours) if cfg.eng_sla_hours else eng_sla_baseline(d)
    now = pd.Timestamp(wall_now) if wall_now is not None else pd.Timestamp.now()
    d["eng_hours"] = np.where(d.tracked, d.eng_done_h + np.where(with_eng & d.eng_entered_at.notna(),
                              (now - d.eng_entered_at).dt.total_seconds() / 3600, 0.0), np.nan)
    measured = d.tracked & (d.eng_hours > d.eng_sla_h)
    proxy = ~d.tracked & with_eng & (d.age_h > d.eng_sla_h)
    d["eng_lag"] = d.lag_marked.astype(bool) | measured | proxy
    d["lag_basis"] = np.select([d.lag_marked.astype(bool), measured, proxy], ["Marked by a lead", "Measured", "Proxy: age since creation"], "")
    d["lag_delay_h"] = np.select([measured, proxy], [d.eng_hours - d.eng_sla_h, d.age_h - d.eng_sla_h], 0.0)
    return d


# ---------- reopen risk (the Back-tests page shows how well it predicts unseen tickets) ----------

def _smoothed_rate(train, col, target, k=SMOOTHING):
    p = train[target].mean()
    g = train.groupby(col)[target].agg(["sum", "count"])
    return ((g["sum"] + k * p) / (g["count"] + k)).to_dict(), p


def fit_reopen(train: pd.DataFrame, flag_share: float = Settings.reopen_flag_share):
    """Return a scoring function built from closed tickets: mean of category and agent reopen rates."""
    closed = train[train.first_closed_at.notna()]
    maps = {c: _smoothed_rate(closed, c, "reopened") for c in ("category", "assigned_agent")}

    def score(x: pd.DataFrame) -> pd.Series:
        return pd.concat([x[c].map(m).astype(float).fillna(p) for c, (m, p) in maps.items()], axis=1).mean(axis=1)

    cut = score(closed).quantile(1 - flag_share)
    return score, cut


def auc(y, s) -> float:
    y = np.asarray(y, bool)
    r = pd.Series(np.asarray(s, float)).rank().values
    n1, n0 = y.sum(), (~y).sum()
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


# ---------- attention flags for open tickets ----------

FLAG_WEIGHTS = {   # how much each flag adds to a ticket's attention score (a ranking choice, shown on Methodology)
    "Overdue, engineering lane": 3,
    "Overdue, L1 lane": 3,
    "Returned by eng, waiting on L1": 2,
    "Bounced 2+ times": 2,
    "Reopened by client": 2,
    "No first response": 2,
    "P1/P2": 1,
    "High impact, low priority": 1,
    "Reopen risk: confirm before closing": 1,
    "At-risk accounts": 0,               # filters only: adding them to the score would change the existing ranking
    "Tickets open 7+ days": 0,
    "Call required: engineering + agent": 0,
}


# What each flag is called in pills, columns and badges, and what it means in full (shown in the legend and as tooltips).
FLAG_SHORT = {
    "Overdue, engineering lane": "Overdue · eng",
    "Overdue, L1 lane": "Overdue · L1",
    "Returned by eng, waiting on L1": "Returned to L1",
    "Bounced 2+ times": "Bounced",
    "Reopened by client": "Reopened",
    "No first response": "No reply yet",
    "P1/P2": "P1/P2",
    "High impact, low priority": "High impact",
    "Reopen risk: confirm before closing": "Reopen risk",
    "At-risk accounts": "At-risk account",
    "Tickets open 7+ days": "Open 7+ days",
    "Call required: engineering + agent": "Call required",
}
FLAG_HELP = {
    "Overdue, engineering lane": "Escalated and still open past the escalated deadline (Policy settings).",
    "Overdue, L1 lane": "Not escalated and still open past the L1 deadline (Policy settings).",
    "Returned by eng, waiting on L1": "Engineering sent it back and L1 has not acted yet.",
    "Bounced 2+ times": "It has gone to engineering more than once.",
    "Reopened by client": "The client reopened it after it was closed.",
    "No first response": "Nobody has replied to the client yet.",
    "P1/P2": "Rated critical or high.",
    "High impact, low priority": "Many people are affected but it is rated P3 or P4.",
    "Reopen risk: confirm before closing": "Tickets like this reopen more than most: confirm the fix with the client before closing.",
    "At-risk accounts": "The client has several bad experiences in the at-risk window (Policy settings).",
    "Tickets open 7+ days": "Open for more than a week.",
    "Call required: engineering + agent": "Second escalation or later: it cannot go back to support. Engineer and agent talk and record the call.",
}


def short_flag(flag: str) -> str:
    return FLAG_SHORT.get(flag, flag)


def high_impact_threshold(d: pd.DataFrame, cfg: Settings | None = None) -> float:
    """People affected at or above which a ticket counts as high impact: the top `high_impact_share` of the data."""
    cfg = cfg or Settings()
    a = d.affected.dropna()
    return float(a.quantile(1 - cfg.high_impact_share)) if len(a) else float("inf")


def attention(d: pd.DataFrame, reopen_score, reopen_cut, cfg: Settings | None = None) -> pd.DataFrame:
    cfg = cfg or Settings()
    o = d[d.is_open].copy()
    f = pd.DataFrame(index=o.index)
    f["Overdue, engineering lane"] = o.esc & (o.age_h > cfg.eng_hours)
    f["Overdue, L1 lane"] = ~o.esc & (o.age_h > cfg.l1_hours)
    f["Returned by eng, waiting on L1"] = o.esc & o.status.eq("Open - with L1")
    f["Bounced 2+ times"] = o.bounced
    f["Reopened by client"] = o.reopened
    f["No first response"] = o.first_response_at.isna()
    f["P1/P2"] = o.priority.isin(["P1", "P2"])
    f["High impact, low priority"] = (o.affected >= high_impact_threshold(d, cfg)) & o.priority.isin(["P3", "P4"])
    f["Reopen risk: confirm before closing"] = reopen_score(o) >= reopen_cut
    f["At-risk accounts"] = o.at_risk
    f["Tickets open 7+ days"] = o.long_open
    f["Call required: engineering + agent"] = o.call_required
    o["attention_score"] = sum(f[c] * w for c, w in FLAG_WEIGHTS.items())
    o["flags"] = f.apply(lambda r: "; ".join(c for c in f.columns if r[c]), axis=1)
    o = o.join(f)
    return o.sort_values(["attention_score", "age_h"], ascending=False)


# ---------- metric tree ----------

def open_stock(d: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """Open tickets at end of each day (stock starts at 0 on the first day of data)."""
    days = pd.date_range(d.created_at.min().normalize(), as_of.normalize(), freq="D")
    ends = days + pd.Timedelta(hours=23, minutes=59)
    c = d.created_at.values
    f = d.final_closed_at.values
    vals = [int(((c <= t) & (pd.isna(f) | (f > t))).sum()) for t in ends.values]
    return pd.Series(vals, index=days, name="open_tickets")


COUNT_KEYS = {"Tickets", "Duplicate escalations", "Avoidable escalations per 100 tickets",
              "Avg handoffs per escalation", "CSAT (avg)", "First response median (h)"}


WHOLE_KEYS = {"Tickets", "Duplicate escalations"}      # counts of tickets: no decimals


def fmt_metric(key, v) -> str:
    if pd.isna(v):
        return "–"
    if key in WHOLE_KEYS:
        return f"{v:,.0f}"
    return f"{v:,.1f}" if key in COUNT_KEYS else f"{v:.1%}"


def scorecard(d: pd.DataFrame) -> dict:
    """Headline metrics for any slice of tickets."""
    s = d[d.settled]
    e = d[d.esc]
    rated = d.csat_score.dropna()
    n = len(d)
    return {
        "Tickets": n,
        "North star: on-time, no reopen": s.north_star.mean() if len(s) else np.nan,
        "Avoidable escalations per 100 tickets": 100 * d.avoidable.sum() / n if n else np.nan,
        "Avoidable share of escalations": e.avoidable.mean() if len(e) else np.nan,
        "Escalation rate": d.esc.mean() if n else np.nan,
        "Escalated closed on time": (s[s.esc].ttr_h <= s[s.esc].deadline_h).mean() if s.esc.any() else np.nan,
        "Non-escalated closed on time": (s[~s.esc].ttr_h <= s[~s.esc].deadline_h).mean() if (~s.esc).any() else np.nan,
        "Bounce rate (2+ handoffs)": e.bounced.mean() if len(e) else np.nan,
        "Avg handoffs per escalation": e.eng_handoffs.mean() if len(e) else np.nan,
        "Duplicate escalations": int(e.eng_outcome.eq("Duplicate of known issue").sum()),
        "Reopen rate": s.reopened.mean() if len(s) else np.nan,
        "Reopen rate, non-escalated": s[~s.esc].reopened.mean() if (~s.esc).any() else np.nan,
        "CSAT (avg)": rated.mean() if len(rated) else np.nan,
        "CSAT response rate": d.csat_score.notna().mean() if n else np.nan,
        "Escalations ending 'Fixed'": e.eng_outcome.eq("Fixed").mean() if len(e) else np.nan,
        "First response median (h)": d.frt_h.median(),
    }


def weekly(d: pd.DataFrame, cfg: Settings | None = None) -> pd.DataFrame:
    w = (cfg or Settings()).window_weeks
    g = d.groupby("week")
    out = pd.DataFrame({
        "tickets": g.size(),
        "north_star": d[d.settled].groupby("week").north_star.mean(),
        "avoidable_per_100": 100 * g.avoidable.sum() / g.size(),
        "reopen_rate": d[d.settled].groupby("week").reopened.mean(),
        "bounce_rate": d[d.esc].groupby("week").bounced.mean(),
        "frt_median_h": g.frt_h.median(),
    })
    out["north_star_rolling"] = (d[d.settled].groupby("week").north_star.sum().rolling(w, min_periods=1).sum()
                                 / d[d.settled].groupby("week").size().rolling(w, min_periods=1).sum())
    return out


def agent_table(d: pd.DataFrame) -> pd.DataFrame:
    s = d[d.settled]
    last_month = d.month.max()
    t = pd.DataFrame({
        "tickets": d.groupby("assigned_agent").size(),
        f"tickets in {last_month}": d[d.month == last_month].groupby("assigned_agent").size(),
        "open now": d[d.is_open].groupby("assigned_agent").size(),
        "north star": s.groupby("assigned_agent").north_star.mean(),
        "escalation rate": d.groupby("assigned_agent").esc.mean(),
        "avoidable per 100": 100 * d.groupby("assigned_agent").avoidable.sum() / d.groupby("assigned_agent").size(),
        "reopen rate": s.groupby("assigned_agent").reopened.mean(),
        "how-to escalations": d[d.eng_outcome.eq("Not a bug - how-to")].groupby("assigned_agent").size(),
        "CSAT": d.groupby("assigned_agent").csat_score.mean(),
    }).fillna({"open now": 0, "how-to escalations": 0})
    return t.sort_values("north star")


# ---------- known-issue registry and escalation gate ----------

def seed_registry(d: pd.DataFrame, as_of: pd.Timestamp, cfg: Settings | None = None) -> pd.DataFrame:
    """Seed: issue templates engineering marked 'Duplicate of known issue' in the last `registry_days` days."""
    days = (cfg or Settings()).registry_days
    dup = d[d.eng_outcome.eq("Duplicate of known issue") & (d.created_at >= as_of - pd.Timedelta(days=days))]
    reg = (dup.groupby("template")
              .agg(category=("category", "first"), duplicates=("ticket_id", "size"),
                   last_seen=("created_at", "max"), eng_ticket=("eng_ticket_id", "last"))
              .reset_index())
    reg["eng_ticket"] = reg.eng_ticket.fillna("").astype(str)       # all-empty would otherwise be a float column the editor rejects
    reg["status"] = "Known - open"
    reg["workaround / client reply"] = "Known issue, engineering is working on it. We will update you by <date>."
    return reg.sort_values("duplicates", ascending=False)


def backtest_gate(d: pd.DataFrame) -> pd.DataFrame:
    """Replay history: could an AUTOMATIC rule have stopped avoidable escalations?

    Registry rules: block if the same issue template got 'Duplicate of known issue' from
    engineering at least k times in the previous N days. How-to rule: block the How-to category.
    Packet completeness cannot be replayed: the data has no escalation fields.
    Result on this data: no rule beats the base rate by much, so the gate suggests, never blocks.
    """
    e = d[d.esc].sort_values("created_at")
    dup = e[e.eng_outcome.eq("Duplicate of known issue")]
    rows = []

    def row(name, hit):
        s = e[hit]
        rows.append({"rule": name, "would stop": len(s),
                     "duplicates caught": int(s.eng_outcome.eq("Duplicate of known issue").sum()),
                     "avoidable caught": int(s.avoidable.sum()),
                     "real bugs wrongly stopped ('Fixed')": int(s.eng_outcome.eq("Fixed").sum()),
                     "precision (share avoidable)": s.avoidable.mean() if len(s) else np.nan})

    for days in (7, 14, 30):
        for k in (1, 2):
            hit = np.array([((dup.template == t) & (dup.created_at < ts)
                             & (dup.created_at >= ts - pd.Timedelta(days=days))).sum() >= k
                            for t, ts in zip(e.template, e.created_at, strict=True)], dtype=bool)
            row(f"Registry: {k}+ duplicates of same issue in last {days} days", hit)
    row("How-to category -> help article", e.category.eq("How-to / feature request").values)
    row("Baseline: block every escalation", np.ones(len(e), bool))
    return pd.DataFrame(rows)


def backtest_reopen(d: pd.DataFrame) -> dict:
    """Out-of-time test: fit on earlier months, test on the latest settled month."""
    closed = d[d.first_closed_at.notna() & d.settled]
    if closed.empty:
        return None
    split = closed.created_at.max().to_period("M").start_time
    train, test = closed[closed.created_at < split], closed[closed.created_at >= split]
    if train.empty or not test.reopened.any() or test.reopened.all():
        return None
    score, cut = fit_reopen(train)
    s = score(test)
    flag = s >= cut
    y = test.reopened
    return {
        "split": split, "train": len(train), "test": len(test), "auc": auc(y, s),
        "flagged": int(flag.sum()), "base_rate": float(y.mean()),
        "precision": float(y[flag].mean()) if flag.any() else np.nan,
        "recall": float(y[flag].sum() / y.sum()) if y.sum() else np.nan,
    }


SCORE_FIELDS = ["template", "category", "assigned_agent", "channel", "priority", "client_tier"]


def backtest_avoidable_score(d: pd.DataFrame) -> dict | None:
    """Could a score built from past escalations predict which NEW escalations come back as avoidable?

    Fit on escalations before the latest month, test on that month. Each field's history is turned into a smoothed
    avoidable rate; the score is the mean over the fields. AUC 0.5 means no better than chance."""
    e = d[d.esc]
    if e.empty:
        return None
    split = e.created_at.max().to_period("M").start_time
    train, test = e[e.created_at < split], e[e.created_at >= split]
    if len(train) < 20 or test.avoidable.nunique() < 2:
        return None

    def score(cols):
        parts = []
        for c in cols:
            m, p = _smoothed_rate(train, c, "avoidable")
            parts.append(test[c].map(m).astype(float).fillna(p))
        return pd.concat(parts, axis=1).mean(axis=1)

    return {"split": split, "train": len(train), "test": len(test), "base_rate": float(test.avoidable.mean()),
            "auc_issue_type": auc(test.avoidable, score(["template"])),
            "auc_agent": auc(test.avoidable, score(["assigned_agent"])),
            "auc_all_fields": auc(test.avoidable, score(SCORE_FIELDS))}
