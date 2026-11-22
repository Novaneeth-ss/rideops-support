"""Accuracy tests for the 1:1 coaching numbers. Run: python test_coaching.py

The expected values are recomputed here straight from the raw CSV with plain pandas (not through engine.py or
coaching.py), so a mistake in the app's pipeline cannot hide itself. Later checks pin the figures that were
verified by hand, and check that the plain-language findings only say what the numbers support.
"""
import math

import numpy as np
import pandas as pd

import coaching as C
import engine as E

RAW = pd.read_csv("data/rideops_support_tickets.csv")
AS_OF = pd.Timestamp("2026-09-30 23:59")

# ---------- independent recomputation (no app code) ----------
r = RAW.copy()
for c in ("created_at", "first_response_at", "first_closed_at", "final_closed_at"):
    r[c] = pd.to_datetime(r[c])
r["esc"] = r.escalated_to_eng == "Yes"
r["hrs"] = (r.final_closed_at - r.created_at).dt.total_seconds() / 3600
r["ttf"] = (r.first_closed_at - r.created_at).dt.total_seconds() / 3600
r["frt"] = (r.first_response_at - r.created_at).dt.total_seconds() / 3600
r["reopened"] = r.reopen_count > 0
r["avoid"] = r.eng_outcome.isin(["Insufficient info - returned to L1", "Config issue - returned to L1",
                                 "Duplicate of known issue", "Not a bug - how-to", "Not reproducible"])
_gap = ((r.final_closed_at - r.first_closed_at).dt.total_seconds() / 86400)[r.reopen_count > 0].max()
SETTLE = int(math.ceil(_gap)) + 1                       # days a reopen takes to show up, derived from the CSV itself
r["settled"] = r.created_at <= AS_OF - pd.Timedelta(days=SETTLE)
QUICK = r[r.settled & ~r.esc & r.ttf.notna()].ttf.quantile(0.25)   # "closed fast": fastest quarter of first closes
r["ontime"] = np.where(r.esc, r.hrs <= 72, r.hrs <= 24)
r["ns"] = r.ontime & ~r.reopened
r["bounced"] = r.eng_handoffs >= 2
AGENTS = sorted(r.assigned_agent.unique())

d = E.enrich(E.load("data/rideops_support_tickets.csv"), AS_OF)
s_, c_ = E.fit_reopen(d[d.settled])
att = E.attention(d, s_, c_)
P = {a: C.profile(d, att, a) for a in AGENTS}


def close(a, b, tol=1e-9):
    return (pd.isna(a) and pd.isna(b)) or math.isclose(a, b, rel_tol=tol, abs_tol=tol)


fails = 0
for a in AGENTS:
    mine, peers = r[r.assigned_agent == a], r[r.assigned_agent != a]
    m = P[a]["metrics"]
    checks = {
        "esc_rate": (mine.esc.mean(), peers.esc.mean(), len(mine)),
        "avoid_per100": (mine.avoid.mean(), peers.avoid.mean(), len(mine)),
        "avoid_share": (mine[mine.esc].avoid.mean(), peers[peers.esc].avoid.mean(), int(mine.esc.sum())),
        "bounce_rate": (mine[mine.esc].bounced.mean(), peers[peers.esc].bounced.mean(), int(mine.esc.sum())),
        "reopen_rate": (mine[mine.settled].reopened.mean(), peers[peers.settled].reopened.mean(), int(mine.settled.sum())),
        "reopen_l1": (mine[mine.settled & ~mine.esc].reopened.mean(), peers[peers.settled & ~peers.esc].reopened.mean(),
                      int((mine.settled & ~mine.esc).sum())),
        "north_star": (mine[mine.settled].ns.mean(), peers[peers.settled].ns.mean(), int(mine.settled.sum())),
        "quick_close": ((mine[mine.settled & ~mine.esc & mine.ttf.notna()].ttf <= QUICK).mean(),
                        (peers[peers.settled & ~peers.esc & peers.ttf.notna()].ttf <= QUICK).mean(),
                        int((mine.settled & ~mine.esc & mine.ttf.notna()).sum())),
        "l1_hours": (mine[~mine.esc].hrs.median(), peers[~peers.esc].hrs.median(), int((~mine.esc & mine.hrs.notna()).sum())),
        "eng_hours": (mine[mine.esc].hrs.median(), peers[peers.esc].hrs.median(), int((mine.esc & mine.hrs.notna()).sum())),
        "frt": (mine.frt.median(), peers.frt.median(), int(mine.frt.notna().sum())),
        "csat": (mine.csat_score.mean(), peers.csat_score.mean(), int(mine.csat_score.notna().sum())),
    }
    for reason, key in C.REASON_KEY.items():
        want = {"Config": "Config issue - returned to L1", "Missing info": "Insufficient info - returned to L1",
                "Duplicate": "Duplicate of known issue", "How-to": "Not a bug - how-to",
                "Not reproducible": "Not reproducible"}[reason]
        checks[key] = ((mine.eng_outcome == want).mean(), (peers.eng_outcome == want).mean(), len(mine))
    for key, (ea, ep, n) in checks.items():
        ok = close(m[key]["agent"], ea) and close(m[key]["peers"], ep) and m[key]["n_agent"] == n
        if not ok:
            fails += 1
            print("MISMATCH", a, key, m[key]["agent"], ea, m[key]["peers"], ep, m[key]["n_agent"], n)
    # counts shown in the findings and mix check
    assert P[a]["tickets"] == len(mine)
    assert P[a]["mix"]["escalated"] == int(mine.esc.sum())
    assert P[a]["mix"]["reopened"] == int(mine[mine.settled].reopened.sum())
    assert int(P[a]["reasons"].sum()) == int((mine.esc & mine.eng_outcome.notna() & (mine.eng_outcome != "Fixed")).sum())
assert fails == 0, fails
print("recomputed every agent x every metric from the raw CSV: match")

# ---------- peers never include the agent; each agent is one of the others' peers ----------
for a in AGENTS:
    pop = C._pop(d, "esc_rate")
    assert (pop[pop.assigned_agent != a].assigned_agent == a).sum() == 0
    assert P[a]["peers"] == len(AGENTS) - 1
print("peer groups exclude the agent: ok")

# ---------- figures verified by hand earlier ----------
R, K, V = P["Rahul T"], P["Karan B"], P["Vikram S"]
assert R["mix"]["escalated"] == 93 and R["tickets"] == 151
assert round(R["metrics"]["esc_rate"]["agent"], 3) == 0.616
assert int(R["reasons"].sum()) == 70 and R["reasons"]["How-to"] == 18 and R["reasons"]["Config"] == 25
assert 46 <= R["mix"]["expected_escalated"] <= 48
cats = R["categories"].set_index("category")
assert cats.loc["Roster / booking not syncing", "escalated"] == 32 and cats.loc["Roster / booking not syncing", "tickets"] == 32
assert cats.loc["Live tracking / GPS incorrect", "escalated"] == 29
assert K["mix"]["reopened"] == 54 and K["metrics"]["reopen_rate"]["n_agent"] == 186
assert round(K["metrics"]["reopen_rate"]["agent"], 3) == 0.290
assert round(V["metrics"]["reopen_rate"]["agent"], 3) == 0.038
print("hand-verified anchors: ok")

# ---------- statistics ----------
assert abs(C.mwu_z([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]) + 2.611) < 0.001          # textbook example
assert C.mwu_z([1, 2, 3], [1, 2, 3]) == 0.0
assert abs(C.mwu_z([6, 7, 8], [1, 2, 3]) + C.mwu_z([1, 2, 3], [6, 7, 8])) < 1e-12   # symmetric
assert abs(C.two_prop_z(30, 100, 20, 100) - 1.6330) < 0.001   # 30% vs 20%, n=100 each: 0.10 / sqrt(.25*.75*(2/100))
assert C.two_prop_z(0, 0, 5, 10) == 0.0 and C.two_prop_z(0, 10, 0, 10) == 0.0
assert abs(C.p_from_z(1.96) - 0.05) < 0.001 and abs(C.p_from_z(2.58) - 0.01) < 0.001
print("statistics: ok")

# ---------- findings only say what the numbers support ----------
def heads(a, kind):
    return [f["headline"] for f in P[a]["findings"][kind]]


assert any("Escalates far more" in h for h in heads("Rahul T", "focus"))
assert any("fixes do not hold" in h for h in heads("Karan B", "focus"))
assert not any("sent back" in h or "returns of one type" in h for h in heads("Karan B", "strengths")), \
    "Karan's low return counts come from escalating less; must not be credited"
assert not P["Priya D"]["findings"]["focus"], "Priya has no gap bigger than chance"
assert any("Fixes hold" in h for h in heads("Vikram S", "strengths"))
assert any("close faster" in h or "on time" in h for h in heads("Arjun K", "strengths"))
assert any("without engineering take longer" in h for h in heads("Sneha M", "focus"))
for a in AGENTS:                                                     # every finding names a real, checkable level
    for f in P[a]["findings"]["focus"] + P[a]["findings"]["strengths"]:
        assert f["level"] in ("clear", "notable") or f["kind"] == "strength"
        assert f["evidence"] and all(isinstance(e, str) and e for e in f["evidence"])
print("findings: ok")

# ---------- small samples are not judged ----------
tiny = d.copy()
only = tiny[tiny.assigned_agent == "Rahul T"].head(10)
small = pd.concat([only, tiny[tiny.assigned_agent != "Rahul T"]])
mm = C.metric(small, "esc_rate", "Rahul T")
assert mm["level"] == "insufficient" and mm["verdict"] == "Not enough data"
solo = d[d.assigned_agent == "Rahul T"]
assert C.metric(solo, "esc_rate", "Rahul T")["level"] == "insufficient"        # no peers at all
print("small samples: ok")

# ---------- review lists and export ----------
rv = K["review"]
assert (rv["reopened"].assigned_agent == "Karan B").all() and rv["reopened"].reopened.all()
assert len(rv["reopened"]) == 54
assert (R["review"]["avoidable"].assigned_agent == "Rahul T").all()
assert len(R["review"]["avoidable"]) == 70 and R["review"]["avoidable"].avoidable.all()
assert (R["review"]["slow_l1"].esc == False).all() and (R["review"]["slow_l1"].ttr_h > 24).all()  # noqa: E712
md = C.to_markdown(R, {"action": "Use the gate", "by": "Fri"})
for needle in ("# 1:1 prep: Rahul T", "61.6%", "Use the gate", "Escalates far more than peers", "| Measure |"):
    assert needle in md, needle
print("review lists + export: ok")
print("coaching tests pass")
