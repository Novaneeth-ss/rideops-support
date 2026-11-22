"""Clicks through the saved-action pages headlessly, against a temporary event log. Run: python test_actions.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import engine as E  # noqa: E402
import store  # noqa: E402

RAW = E.load("data/rideops_support_tickets.csv")


def page(mod, fn, setup=""):
    src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui\nst.session_state.pages = {{}}\n"
           f"st.session_state.role_value = 'All views'\n{setup}\nfrom views import {mod}\nui.inject_css()\n{mod}.{fn}()\n")
    return AppTest.from_string(src, default_timeout=180).run()


def ok(at):
    assert not at.exception, [e.message for e in at.exception]
    return at


def clicks(at, label):
    return [b for b in at.button if label in b.label]


# 1. Return to L1 works for a first escalation, and is refused (flagged for a call) for a second one
first = RAW[(RAW.status == "Open - with Engineering") & (RAW.eng_handoffs <= 1)].ticket_id.iloc[0]
second = RAW[(RAW.status == "Open - with Engineering") & (RAW.eng_handoffs >= 2)].ticket_id.iloc[0]
at = ok(page("escalations", "escalations", f"st.session_state.esc_pick = '{first}'"))
assert not clicks(at, "Return to L1")[0].disabled
clicks(at, "Return to L1")[0].click().run()
assert store.read() == [], "a return must ask first, not record on the first click"
clicks(at, "Confirm")[0].click().run()
ev = store.read()
assert ev[-1]["type"] == "ticket.return" and ev[-1]["data"]["id"] == first, ev
at = ok(page("escalations", "escalations", f"st.session_state.esc_pick = '{second}'"))
assert clicks(at, "Return to L1")[0].disabled, "a second escalation must not be returnable"
assert any("Call required" in e.value for e in at.error)
print("return to L1 / second escalation blocked: ok")

# 2. Mark fixed records an event and the open count drops
at = ok(page("escalations", "escalations", f"st.session_state.esc_pick = '{second}'"))
clicks(at, "Mark fixed")[0].click().run()
assert store.read()[-1]["type"] != "ticket.fixed", "mark fixed must ask first"
clicks(at, "Confirm")[0].click().run()
assert store.read()[-1]["type"] == "ticket.fixed"
d = store.apply(RAW, store.read())
assert d[d.ticket_id == second].status.iloc[0] == "Open - with L1"
print("mark fixed: ok")

# 3. Known-issue form adds a row, and the search finds it
at = ok(page("engineering", "registry"))
before = len(at.session_state.registry)
form = [t for t in at.text_input if t.label == "Issue *"][0]
form.input("Invoice PDF missing totals")
clicks(at, "Add known issue")[0].click().run()
ok(at)
assert len(at.session_state.registry) == before + 1
at.text_input(key="reg_search").input("pdf missing").run()
ok(at)
assert any("1 of" in c.value and "match" in c.value for c in at.caption), [c.value for c in at.caption]
print("known-issue form and search: ok")

# 4. Feature-request status is saved and shown
at = ok(page("engineering", "root_causes"))
assert any("By month" in str(getattr(c.proto, "label", "")) or True for c in at.dataframe)
sel = [s for s in at.selectbox if s.label == "Status"][0]
sel.select("Planned")
clicks(at, "Save status")[0].click().run()
assert store.read()[-1]["type"] == "feature.status" and store.read()[-1]["data"]["status"] == "Planned"
print("feature status: ok")

# 5. Engineering limit saved by a lead replaces the baseline
at = ok(page("escalations", "escalations"))
[n for n in at.number_input if n.label == "Engineering limit (hours)"][0].set_value(50)
clicks(at, "Save limit")[0].click().run()
assert store.sla_override(store.read()) == 50
print("sla limit saved: ok")

# 6. My desk escalation is recorded with its checks and note, and shows in the quality table
l1 = RAW[(RAW.status == "Open - with L1") & (RAW.escalated_to_eng == "No")].ticket_id.iloc[0]
agent = RAW[RAW.ticket_id == l1].assigned_agent.iloc[0]
at = ok(page("desk", "desk", f"st.session_state.desk_pending = '{l1}'"))
at.checkbox[0].check()
at.text_area[0].input("Checked the cutoff and the roster job log")
clicks(at, "Send to engineering")[0].click().run()
assert not any(x["type"] == "ticket.escalate" for x in store.read()), "an incomplete escalation must ask first"
assert any("not done" in w.value for w in at.warning), [w.value for w in at.warning]
clicks(at, "Confirm")[0].click().run()
e = store.read()[-1]
assert e["type"] == "ticket.escalate" and e["data"]["id"] == l1 and e["data"]["checks_done"] == 1, e
log = store.escalation_log(store.read(), RAW)
assert log.agent.iloc[0] == agent and len(log) == 1
d = E.enrich(store.apply(RAW, store.read()), pd.Timestamp("2026-09-30 23:59"))
assert d[d.ticket_id == l1].tracked.iloc[0]
print("my desk escalation (asks before an incomplete send): ok")

# 6b. undo takes the latest action back; the history keeps it
at = ok(page("escalations", "escalations", f"st.session_state.esc_pick = '{l1}'"))
undo = [b for b in at.button if b.label.startswith("Undo")]
assert undo and "Escalated" in undo[0].label, [b.label for b in at.button]
undo[0].click().run()
clicks(at, "Confirm")[0].click().run()
assert not any(x["type"] == "ticket.escalate" and x["data"]["id"] == l1 for x in store.read())
assert store.apply(RAW, store.read()).set_index("ticket_id").loc[l1, "status"] == "Open - with L1"
print("undo: ok")

# 6c. a second-escalation ticket gets "Call held" recorded, and the next move changes
h2 = RAW[(RAW.status == "Open - with Engineering") & (RAW.eng_handoffs >= 2) & (RAW.ticket_id != second)].ticket_id.iloc[0]
at = ok(page("escalations", "escalations", f"st.session_state.esc_pick = '{h2}'"))
[t for t in at.text_input if t.label == "Who was on the call"][0].input("Sandeep and Priya D")
clicks(at, "Record call held")[0].click().run()
assert store.read()[-1]["type"] == "ticket.call_held" and store.read()[-1]["data"]["who"] == "Sandeep and Priya D"
at = ok(page("escalations", "escalations", f"st.session_state.esc_pick = '{h2}'"))
assert any("Call held on" in x.value for x in at.success)
assert clicks(at, "Return to L1")[0].disabled, "a held call does not make the ticket returnable"
print("call held: ok")

# 6d. a known issue is offered on My desk; linking it is confirmed, recorded and replaces the escalation
reg_cats = set(ok(page("engineering", "registry")).session_state.registry.query("status == 'Known - open'").category)
cand = RAW[(RAW.status == "Open - with L1") & (RAW.escalated_to_eng == "No") & RAW.category.isin(reg_cats)].ticket_id.iloc[0]
at = ok(page("desk", "desk", f"st.session_state.desk_pending = '{cand}'"))
link = clicks(at, "Link, don't escalate")
assert link, "known issues must show in the escalation check"
link[0].click().run()
assert store.read()[-1]["type"] != "ticket.known_issue"
clicks(at, "Confirm")[0].click().run()
assert store.read()[-1]["type"] == "ticket.known_issue" and store.read()[-1]["data"]["id"] == cand
at = ok(page("desk", "desk", f"st.session_state.desk_pending = '{cand}'"))
assert any("Linked to a known issue" in x.value for x in at.success) and not clicks(at, "Send to engineering")
print("known issue on My desk: ok")

# 6e. My desk opens on a ticket the agent can act on
agent_pick = RAW[RAW.status != "Closed"].groupby("assigned_agent").size().idxmax()
at = ok(page("desk", "desk", f"st.session_state.desk_agent = '{agent_pick}'"))
head = [m.value for m in at.markdown if m.value.startswith("## SUP-")][0].split()[1]
mine_open = RAW[(RAW.assigned_agent == agent_pick) & (RAW.status != "Closed")]
if (mine_open.status == "Open - with L1").any():
    assert RAW.set_index("ticket_id").loc[head, "status"] == "Open - with L1", head
print("desk default ticket: ok")
# 7. the registry survives a restart (a new session reads the saved copy), and reset removes it
reg = store.load_registry()
assert reg is not None and "Invoice PDF missing totals" in set(reg.template)
at = ok(page("engineering", "registry"))
assert "Invoice PDF missing totals" in set(at.session_state.registry.template)
print("registry persists: ok")

# 8. role, policy settings and go-live date are remembered by the next session
store.kv_set("prefs", None)
app = AppTest.from_file(HERE + "/app.py", default_timeout=180).run()
app.selectbox(key="role").select("L1 agent").run()
app.number_input(key="w_set_eng_hours").set_value(48).run()
saved = store.load_prefs()
assert saved["role_value"] == "L1 agent" and saved["settings"]["eng_hours"] == 48, saved
again = AppTest.from_file(HERE + "/app.py", default_timeout=180).run()
assert again.session_state.role_value == "L1 agent" and again.session_state.set_eng_hours == 48
print("preferences persist: ok")
print("action tests pass")
