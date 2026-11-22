"""Everything saved survives a restart, is kept per dataset, and API data is fetched and saved.
Uses a temporary database. Run: python test_persistence.py"""
import http.server
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ["RIDEOPS_API_ALLOW_PRIVATE"] = "1"      # these tests call a server on 127.0.0.1
os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()
os.environ.pop("DATABASE_URL", None)
import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import connect  # noqa: E402
import engine as E  # noqa: E402
import store  # noqa: E402

RAW_BYTES = open("data/rideops_support_tickets.csv", "rb").read()  # noqa: SIM115
RAW = E.load("data/rideops_support_tickets.csv")


def page(mod, fn):
    src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui\nst.session_state.pages = {{}}\n"
           f"st.session_state.role_value = 'All views'\nfrom views import {mod}\nui.inject_css()\n{mod}.{fn}()\n")
    at = AppTest.from_string(src, default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


# 1. a saved dataset is the one every new session uses, and the sample comes back on request
assert store.active_key() == store.SAMPLE and store.active_dataset() is None
sub = RAW_BYTES.decode("utf-8").splitlines()
small = ("\n".join(sub[:1] + sub[1:301]) + "\n").encode()
ds_id = store.save_dataset("small.csv", small, "upload")
app = AppTest.from_file(HERE + "/app.py", default_timeout=180).run()
assert not app.exception and any("small.csv" in str(m.value) for m in app.get("html")), "data name not shown"
assert store.active_key() == str(ds_id) and store.list_datasets()[0]["name"] == "small.csv"
print("saved upload is used by a new session: ok")

# 2. it survives a restart (a new connection to the same database)
store._engine.cache_clear()
assert store.active_dataset()["name"] == "small.csv" and store.dataset_content(ds_id) == small
print("survives restart: ok")

# 3. actions and the registry are kept per dataset
first = RAW[RAW.ticket_id.isin(pd.read_csv(__import__("io").BytesIO(small)).ticket_id)]
l1 = first.ticket_id.iloc[0]
store.append("ticket.escalate", "Priya D", {"id": l1, "note": "n" * 25, "checks_done": 1, "checks_total": 2})
assert len(store.read()) == 1
store.save_registry(pd.DataFrame([{"template": "A known issue", "category": "x", "status": "Known - open", "eng_ticket": "",
                                   "duplicates": 0, "last_seen": None, "workaround / client reply": ""}]))
store.set_active(None)                                          # back to the sample
assert store.active_key() == store.SAMPLE and store.read() == [] and store.load_registry() is None
store.set_active(ds_id)
assert len(store.read()) == 1 and list(store.load_registry().template) == ["A known issue"]
print("events and registry are per dataset: ok")

# 4. a 1:1 agreement is saved and comes back in a new session
store.set_active(None)
at = page("oneonone", "agent_one_on_one")
agent = at.session_state.oo_agent
[t for t in at.text_input if t.label == "One action we agree"][0].input("Run the gate checklist").run()
assert store.kv_get(f"oo:{agent}", None, ds=None)["action"] == "Run the gate checklist"
store._engine.cache_clear()
at2 = page("oneonone", "agent_one_on_one")
assert [t for t in at2.text_input if t.label == "One action we agree"][0].value == "Run the gate checklist"
print("1:1 agreement persists: ok")

# 5. API: CSV and JSON, token header, errors
seen = {}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        seen["auth"] = self.headers.get("Authorization")
        seen["x"] = self.headers.get("X-Key")
        if self.path == "/csv":
            body, kind = small, "text/csv"
        elif self.path == "/json":
            recs = pd.read_csv(__import__("io").BytesIO(small)).head(5).where(lambda d: d.notna(), None).to_dict("records")
            body, kind = json.dumps({"tickets": recs}).encode(), "application/json"
        elif self.path == "/nolist":
            body, kind = b'{"meta": 1}', "application/json"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
got = connect.fetch(base + "/csv", token="abc")
assert got == small and seen["auth"] == "Bearer abc"
connect.fetch(base + "/csv", "X-Key", "k1")
assert seen["x"] == "k1"
j = connect.fetch(base + "/json")
df = E.load(__import__("io").BytesIO(j))
assert len(df) == 5 and "ticket_id" in df
for bad, why in ((base + "/nolist", "no list"), (base + "/missing", "404"), ("ftp://x/y", "scheme")):
    try:
        connect.fetch(bad)
        raise AssertionError("accepted " + why)
    except (OSError, ValueError):
        pass
os.environ["RIDEOPS_API_ALLOWED_HOSTS"] = "example.com"
try:
    connect.fetch(base + "/csv")
    raise AssertionError("allow-list ignored")
except ValueError:
    pass
os.environ.pop("RIDEOPS_API_ALLOWED_HOSTS")
srv.shutdown()
print("api fetch: ok")

# 6. the fetched data can be saved and used like an upload
new_id = store.save_dataset("api test", got, "api")
assert store.active_key() == str(new_id) and store.list_datasets()[0]["source"] == "api"
d = E.load(__import__("io").BytesIO(store.dataset_content(new_id)))
assert len(d) == 300
print("api data saved: ok")

# 7. a hosted database: the old postgres:// scheme is accepted
os.environ["DATABASE_URL"] = "postgres://u:p@h:5432/db"
assert store.database_url() == "postgresql://u:p@h:5432/db?sslmode=require", "a remote database is encrypted by default"
os.environ["DATABASE_URL"] = "postgresql://u:p@h:5432/db?sslmode=disable"
assert store.database_url().endswith("sslmode=disable"), "an explicit choice is kept"
os.environ["DATABASE_URL"] = "postgresql://u:p@localhost:5432/db"
assert "sslmode" not in store.database_url(), "local databases are left alone"
os.environ["DATABASE_URL"] = "postgresql://u:p@/db?host=/tmp/sock"
assert "sslmode" not in store.database_url(), "socket paths are left alone"
os.environ.pop("DATABASE_URL")
# 8. many sessions writing at once, starting from an empty database, lose nothing (found by the full audit)
import threading  # noqa: E402

os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()
store._engine.cache_clear()
errs = []


def _work(k):
    for i in range(40):
        try:
            store.append("ticket.lag_mark", f"u{k}", {"id": f"SUP-{k}-{i}"})
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))


ts = [threading.Thread(target=_work, args=(k,)) for k in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
assert not errs and len(store.read()) == 320, (errs[:2], len(store.read()))
print("concurrent writers: ok")
print("persistence tests pass")
