"""Security checks: private-network API targets, redirects, HTML in data, admin-only data and policy. Run: python test_security.py"""
import http.server
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()
os.environ.pop("RIDEOPS_API_ALLOW_PRIVATE", None)
os.environ.pop("RIDEOPS_REQUIRE_LOGIN", None)
import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import connect  # noqa: E402
import ui  # noqa: E402

# 1. the server may not be pointed at its own network
for url in ("http://127.0.0.1:9/x", "http://localhost:9/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/x",
            "http://192.168.1.1/x", "http://[::1]/x", "file:///etc/passwd", "ftp://example.com/x"):
    try:
        connect.check_url(url)
        raise AssertionError(f"accepted {url}")
    except ValueError:
        pass
print("private targets refused: ok")


# 2. redirects are not followed (a public host could bounce the server to an internal one)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/jump":
            self.send_response(302)
            self.send_header("Location", "/csv")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.end_headers()
            self.wfile.write(b"a,b\n1,2\n")

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ["RIDEOPS_API_ALLOW_PRIVATE"] = "1"
assert connect.fetch(base + "/csv") == b"a,b\n1,2\n"
try:
    connect.fetch(base + "/jump")
    raise AssertionError("followed a redirect")
except OSError:
    pass
srv.shutdown()
os.environ.pop("RIDEOPS_API_ALLOW_PRIVATE")
print("redirects refused: ok")

# 3. HTML in the data is shown as text, never run
evil = '<img src=x onerror=alert(1)>'
assert "<img" not in ui.badge(evil, "warn", evil) and "&lt;img" in ui.badge(evil)
raw = pd.read_csv("data/rideops_support_tickets.csv", dtype=str, keep_default_na=False)
raw.loc[raw.status != "Closed", "description"] = evil
raw.loc[raw.status != "Closed", "client_name"] = "<script>alert(1)</script>"
path = os.path.join(tempfile.mkdtemp(), "evil.csv")
raw.to_csv(path, index=False)
for mod, fn, plain in (("support", "attention_queue", True), ("desk", "desk", False), ("health", "account_health", True),
                       ("escalations", "escalations", True)):
    src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui, state\nst.session_state.pages = {{}}\n"
           f"st.session_state.role_value = 'All views'\nst.session_state.raw = open(r'{path}', 'rb').read()\n"
           f"st.session_state.plain_tables = {plain}\nfrom views import {mod}\nui.inject_css()\n{mod}.{fn}()\n"
           "t = state.context().att.ticket_id.iloc[0]\nstate.render_ticket(t)\n")
    at = AppTest.from_string(src, default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    for h in at.get("html"):
        v = str(h.value)
        assert "<img src=x" not in v and "<script>alert" not in v, f"{mod}: data reached the page as HTML"
print("html in data escaped: ok")

# 4. with sign-in on, only administrators see the shared Data and Policy settings
import auth  # noqa: E402

os.environ["RIDEOPS_REQUIRE_LOGIN"] = "1"
auth.create_user("boss", "Boss", "Admin", "a long password 1")
auth.create_user("agent", "Agent One", "L1 agent", "agent long password")


def labels(user):
    app = AppTest.from_file(HERE + "/app.py", default_timeout=180)
    app.session_state.user = user
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    return [e.label.split(" · ")[0] for e in app.sidebar.expander]


assert {"Data", "Policy settings"} <= set(labels({"username": "boss", "name": "Boss", "role": "Admin"}))
others = labels({"username": "agent", "name": "Agent One", "role": "L1 agent"})
assert "Data" not in others and "Policy settings" not in others, others
print("admin-only data and policy: ok")
print("security tests pass")
