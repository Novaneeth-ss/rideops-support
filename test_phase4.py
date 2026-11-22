"""Phase 4: plain tables, account call records, API mapping in the app. Run: python test_phase4.py"""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ["RIDEOPS_API_ALLOW_PRIVATE"] = "1"      # these tests call a server on 127.0.0.1
os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()
os.environ.pop("RIDEOPS_REQUIRE_LOGIN", None)
import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import connect  # noqa: E402
import engine as E  # noqa: E402
import store  # noqa: E402


def page(mod, fn, setup=""):
    src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui\nst.session_state.pages = {{}}\n"
           f"st.session_state.role_value = 'All views'\n{setup}\nfrom views import {mod}\nui.inject_css()\n{mod}.{fn}()\n")
    at = AppTest.from_string(src, default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


# 1. plain tables: every page still renders, tables become real HTML, ticket tables get a picker
PAGES = [("overview", "scorecard"), ("support", "attention_queue"), ("support", "agent_coaching"), ("desk", "desk"),
         ("health", "account_health"), ("escalations", "escalations"), ("engineering", "returns"), ("engineering", "registry"),
         ("engineering", "root_causes"), ("insights", "before_after"), ("insights", "backtests"), ("insights", "methodology")]
for mod, fn in PAGES:
    page(mod, fn, "st.session_state.plain_tables = True")
at = page("support", "attention_queue", "st.session_state.plain_tables = True")
assert [s for s in at.selectbox if s.label == "Open a ticket"], "plain ticket tables need a way to open a ticket"
tbl = [str(h.value) for h in at.get("html") if "<table" in str(h.value) and "Attention" in str(h.value)]
assert tbl and "<th" in tbl[0], "the ticket table must be a real HTML table"
assert "Overdue · eng" in tbl[0] or "Bounced" in tbl[0], "flags must read as text"
print("plain tables: ok")

# 2. a call to an at-risk account is recorded, shown in the table, and can be taken back
at = page("health", "account_health")
before = at.dataframe[0].value
client = before.client.iloc[0]
assert (before.last_called == "Not called yet").all()
src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui\nst.session_state.pages = {{}}\n"
       f"from views import health\nhealth._contact({client!r})\n")
c = AppTest.from_string(src, default_timeout=120).run()
assert not c.exception and any("Nobody has recorded a call" in w.value for w in c.warning)
c.text_input[0].input("Left a message with the admin")
[b for b in c.button if "Record that I called" in b.label][0].click().run()
ev = store.read()[-1]
assert ev["type"] == "account.called" and ev["data"]["client"] == client and ev["data"]["note"] == "Left a message with the admin"
after = page("health", "account_health").dataframe[0].value
row = after[after.client == client].iloc[0]
assert row.last_called != "Not called yet" and row.called_by
c = AppTest.from_string(src, default_timeout=120).run()
assert any("Called on" in s.value for s in c.success)
[b for b in c.button if "Undo the last call record" in b.label][0].click().run()
[b for b in c.button if b.label == "Confirm"][0].click().run()
assert store.read() == [], "undo must remove the call record from the effective history"
print("account called: ok")

# 3. the app asks for the missing fields and loads the data once they are mapped
raw = pd.read_csv("data/rideops_support_tickets.csv", dtype=str, keep_default_na=False).head(150)
renamed = raw.rename(columns={"ticket_id": "TicketID", "created_at": "Created", "assigned_agent": "Assignee", "status": "State"})
store.kv_set("api", {"url": "http://example.test/tickets", "header": "Authorization"})
app = AppTest.from_file(HERE + "/app.py", default_timeout=180)
app.session_state.api_pending = connect.to_bytes(renamed)
app.run()
assert not app.exception, [e.message for e in app.exception]
gaps = [s for s in app.sidebar.selectbox if s.label in ("ticket_id", "created_at", "assigned_agent", "status")]
assert len(gaps) == 4, [s.label for s in app.sidebar.selectbox]
for s in gaps:
    if s.label == "status":
        s.select("State")
    elif s.label == "assigned_agent":
        s.select("Assignee")
app.run()
save = [b for b in app.sidebar.button if b.label == "Save mapping and load"][0]
assert save.disabled is False
save.click().run()
assert not app.exception, [e.message for e in app.exception]
ds = store.list_datasets()
assert len(ds) == 1 and ds[0]["source"] == "api", ds
assert store.kv_get("api")["mapping"]["status"] == "State"
assert len(E.load(io.BytesIO(store.dataset_content(ds[0]["id"])))) == 150
print("api mapping in the app: ok")
print("phase 4 tests pass")
