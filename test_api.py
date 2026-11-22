"""API field mapping and the scheduled refresh script. Run: python test_api.py"""
import http.server
import io
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
import pandas as pd  # noqa: E402

import connect  # noqa: E402
import engine as E  # noqa: E402
import refresh  # noqa: E402
import store  # noqa: E402

RAW = pd.read_csv("data/rideops_support_tickets.csv", dtype=str, keep_default_na=False).head(120)
# an API that names its fields differently
RENAMED = RAW.rename(columns={"ticket_id": "TicketID", "created_at": "Created", "assigned_agent": "Assignee", "status": "State"})
assert connect.missing(RENAMED, E.REQUIRED) == ["ticket_id", "created_at", "assigned_agent", "status"]

# 1. the closest names are suggested; names nothing resembles are left for a person
guess = connect.suggest(list(RENAMED.columns), connect.missing(RENAMED, E.REQUIRED))
assert guess["ticket_id"] == "TicketID" and guess["created_at"] == "Created", guess
assert guess["status"] is None, guess      # too different to guess: a person chooses
print("suggest: ok")

# 2. a mapping makes the table readable as an export, and leaves existing fields alone
mapped = connect.apply_mapping(RENAMED, {"ticket_id": "TicketID", "created_at": "Created", "assigned_agent": "Assignee",
                                         "status": "State", "priority": "nonexistent"})
assert not connect.missing(mapped, E.REQUIRED)
assert (mapped.priority == RENAMED.priority).all(), "an existing field must not be overwritten"
df = E.load(io.BytesIO(connect.to_bytes(mapped)))
assert len(df) == len(RAW) and set(df.ticket_id) == set(RAW.ticket_id)
print("mapping: ok")


# 3. the refresh script, against a local API
class H(http.server.BaseHTTPRequestHandler):
    body = json.dumps({"tickets": RENAMED.to_dict("records")}).encode()
    seen = {}

    def do_GET(self):
        H.seen["auth"] = self.headers.get("Authorization")
        if self.path != "/tickets":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(H.body)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"

assert refresh.main() == 1 and "no API connection" in store.kv_get("api_last")["message"]
store.kv_set("api", {"url": base + "/tickets", "header": "Authorization"})
assert refresh.main("tok") == 1 and "fields missing" in store.kv_get("api_last")["message"], "must refuse unmapped data"
assert store.list_datasets() == [], "nothing may be saved when the data does not map"
store.kv_set("api", {"url": base + "/tickets", "header": "Authorization", "mapping": {
    "ticket_id": "TicketID", "created_at": "Created", "assigned_agent": "Assignee", "status": "State"}})
assert refresh.main("tok") == 0 and H.seen["auth"] == "Bearer tok"
assert len(store.list_datasets()) == 1 and store.list_datasets()[0]["source"] == "api"
assert "saved 120 tickets" in store.kv_get("api_last")["message"]
assert refresh.main("tok") == 0 and len(store.list_datasets()) == 1, "unchanged data must not be saved again"
assert "no change" in store.kv_get("api_last")["message"]
store.kv_set("api", {"url": base + "/missing", "header": "Authorization"})
assert refresh.main() == 1 and "failed" in store.kv_get("api_last")["message"] and len(store.list_datasets()) == 1
srv.shutdown()
print("scheduled refresh: ok")
print("api tests pass")
