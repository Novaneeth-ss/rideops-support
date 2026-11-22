"""Self-check: engine reproduces the numbers from the diagnosis. Run: python test_engine.py"""
import pandas as pd

import engine as E

AS_OF = pd.Timestamp("2026-09-30 23:59")
d = E.enrich(E.load("data/rideops_support_tickets.csv"), AS_OF)

assert len(d) == 1444
assert d.esc.sum() == 486 and d.avoidable.sum() == 275
assert d.is_open.sum() == 48
assert d.settled.sum() == 1285                       # tickets created up to 22 Sep
assert round(d[d.settled].north_star.mean(), 3) == 0.628

sc = E.scorecard(d)
assert round(sc["Avoidable escalations per 100 tickets"], 1) == 19.0
assert round(sc["Bounce rate (2+ handoffs)"], 3) == 0.471

score, cut = E.fit_reopen(d[d.settled])
a = E.attention(d, score, cut)
assert len(a) == 48
assert a["Overdue, engineering lane"].sum() == 15
assert a["Overdue, L1 lane"].sum() == 5
assert a["Returned by eng, waiting on L1"].sum() == 15
assert a["Reopened by client"].sum() == 9
assert a["No first response"].sum() == 5

r = E.backtest_reopen(d)
assert r["split"] == pd.Timestamp("2026-09-01") and 0.68 < r["auc"] < 0.76, r

assert E.fmt_metric("Avg handoffs per escalation", 1.0) == "1.0"     # not "100.0%"
assert E.fmt_metric("Duplicate escalations", 1) == "1"      # a count of tickets: no decimals
assert E.fmt_metric("Reopen rate", 0.1) == "10.0%"

# small export (fewer than 4 settled weeks) must not crash the engine
sm = E.enrich(E.load("data/rideops_support_tickets.csv").head(60), pd.Timestamp("2026-07-05 23:59"))
assert E.weekly(sm).north_star.isna().all() and E.backtest_reopen(sm) is None

g = E.backtest_gate(d)
base = g[g.rule.str.startswith("Baseline")].iloc[0]
assert base["would stop"] == 486 and base["avoidable caught"] == 275 and base["real bugs wrongly stopped ('Fixed')"] == 211
assert (g["would stop"] == g["avoidable caught"] + g["real bugs wrongly stopped ('Fixed')"]).all()

stock = E.open_stock(d, AS_OF)
assert stock.iloc[-1] == 48

print("all checks pass")
print(g.round(3).to_string())
print("reopen back-test:", r)
print(E.agent_table(d).round(3).to_string())
print(E.seed_registry(d, AS_OF)[["template", "duplicates"]].to_string())

# every flag shown in the queue is a known flag name (names may contain commas, so join with "; ")
assert set(x for v in a["flags"] for x in v.split("; ") if x) <= set(E.FLAG_WEIGHTS)
print("flag check pass")
