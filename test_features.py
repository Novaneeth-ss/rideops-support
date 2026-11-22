"""Tests for the saved-action features: escalation tracking, the second-escalation rule, lag and SLA, new flags,
counts matching their lists. Uses a temporary event log, never the real one. Run: python test_features.py"""
import os
import tempfile

os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()      # never the real database
import pandas as pd  # noqa: E402

import engine as E  # noqa: E402
import store  # noqa: E402

RAW = E.load("data/rideops_support_tickets.csv")
AS_OF = RAW.created_at.max().normalize() + pd.Timedelta(hours=23, minutes=59)
LOG = "feat_test"      # a dataset key of its own


def build(events):
    return E.enrich(store.apply(RAW, events), AS_OF, E.Settings())


# 1. nothing is back-filled: with an empty log no ticket is "tracked" and no tracking column is invented
d0 = build([])
assert not d0.tracked.any() and d0.eng_entered_at.isna().all() and d0.eng_hours.isna().all()
assert not d0.lag_marked.any() and d0.eng_head_at.isna().all()
print("no back-fill: ok")

# 2. escalating records time, note and checks, and moves the ticket to engineering
l1 = RAW[(RAW.status == "Open - with L1") & (RAW.escalated_to_eng == "No")].ticket_id.iloc[0]
store.append("ticket.escalate", "Priya D", {"id": l1, "note": "x" * 30, "checks_done": 2, "checks_total": 4}, LOG)
d1 = build(store.read(LOG))
r = d1[d1.ticket_id == l1].iloc[0]
assert r.status == "Open - with Engineering" and r.tracked and r.eng_handoffs == 1 and r.checks_done == 2
assert r.eng_ticket_id.startswith("ENG-") and pd.notna(r.eng_entered_at) and r.eng_hours >= 0
assert d1.tracked.sum() == 1                                           # only that ticket
print("escalation recorded: ok")

# 3. a ticket on its 2nd escalation cannot be returned: it is flagged for a call instead
h2 = RAW[(RAW.status == "Open - with Engineering") & (RAW.eng_handoffs >= 2)].ticket_id.iloc[0]
store.append("ticket.return", "Eng", {"id": h2, "reason": store.RETURN_REASONS[0]}, LOG)
d2 = build(store.read(LOG))
r = d2[d2.ticket_id == h2].iloc[0]
assert r.status == "Open - with Engineering" and r.call_required, "a 2nd escalation must not bounce back"
# a first escalation can be returned, and the time it spent with engineering is kept
store.append("ticket.return", "Eng", {"id": l1, "reason": store.RETURN_REASONS[1]}, LOG)
d3 = build(store.read(LOG))
r = d3[d3.ticket_id == l1].iloc[0]
assert r.status == "Open - with L1" and r.eng_outcome == store.RETURN_REASONS[1] and pd.notna(r.eng_left_at) and r.eng_hours >= 0
print("second escalation cannot be returned: ok")

# 4. flags: at-risk, open 7+ days and call required agree with their definitions
att = E.attention(d0, lambda x: pd.Series(0.0, index=x.index), 1.0)
cfg = E.Settings()
risky = E.at_risk_clients(d0, AS_OF, cfg)
assert set(att[att["At-risk accounts"]].client_name) <= set(risky.index)
assert (att[att["Tickets open 7+ days"]].age_h > E.LONG_OPEN_DAYS * 24).all()
assert int(att["Tickets open 7+ days"].sum()) == int((d0[d0.is_open].age_h > E.LONG_OPEN_DAYS * 24).sum())
assert int(att["Call required: engineering + agent"].sum()) == int(
    (d0[d0.is_open].status.eq("Open - with Engineering") & d0[d0.is_open].eng_handoffs.ge(2)).sum())
# the new flags do not change the existing ranking
assert all(E.FLAG_WEIGHTS[f] == 0 for f in ("At-risk accounts", "Tickets open 7+ days", "Call required: engineering + agent"))
print("flags: ok")

# 5. SLA: the baseline is the 75th percentile of closed escalated tickets, and a saved limit overrides it
x = d0[d0.esc & d0.ttr_h.notna()].ttr_h
assert abs(E.eng_sla_baseline(d0) - x.quantile(0.75)) < 1e-9
assert (d0.eng_sla_h == E.eng_sla_baseline(d0)).all()
d4 = E.enrich(store.apply(RAW, []), AS_OF, E.Settings(eng_sla_hours=48))
assert (d4.eng_sla_h == 48).all() and d4.eng_lag.sum() >= d0.eng_lag.sum()
store.append("config.eng_sla", "Lead", {"hours": 60}, LOG)
assert store.sla_override(store.read(LOG)) == 60
print("sla: ok")

# 6. escalation quality counts only saved escalations, and starts at the first one
log = store.escalation_log(store.read(LOG), RAW)
assert len(log) == 1 and log.agent.iloc[0] == "Priya D" and log.checks_done.iloc[0] < log.checks_total.iloc[0]
assert log.when.min() == pd.Timestamp(store.read(LOG)[0]["at"])
print("escalation quality: ok")

# 7. invalid events are rejected and a damaged line does not break reading
for bad in ({"id": l1, "reason": "made up"},):
    try:
        store.append("ticket.return", "Eng", bad, LOG)
        raise AssertionError("accepted a bad reason")
    except ValueError:
        pass
from sqlalchemy import insert  # noqa: E402
with store._db().begin() as c:
    c.execute(insert(store._events).values(ds=LOG, at="x", type="ticket.fixed", by="x", data="{not json"))
assert len(store.read(LOG)) == 4
print("log validation: ok")
# 8. small and odd data must not crash the helpers (found by the full audit)
import coaching  # noqa: E402

none_esc = RAW.assign(escalated_to_eng="No", eng_ticket_id=None, eng_handoffs=0, eng_outcome=None)
reg = E.seed_registry(E.enrich(none_esc, AS_OF), AS_OF)
assert reg.empty and not pd.api.types.is_float_dtype(reg.eng_ticket), "an empty registry keeps text columns text"
tiny = E.enrich(RAW.head(40), AS_OF)
ct = coaching.category_table(tiny, tiny.assigned_agent.iloc[0])
assert ct.empty and "esc_z" in ct.columns, "an empty category table keeps its columns"
print("small data: ok")
print("feature tests pass")
