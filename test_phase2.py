"""Phase 2 UX changes: welcome once, search results, changed-setting markers, account health filters. Run: python test_phase2.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()
from streamlit.testing.v1 import AppTest  # noqa: E402

import store  # noqa: E402


def app():
    return AppTest.from_file(HERE + "/app.py", default_timeout=180).run()


def welcome(at):
    return any("Start here" in str(h.value) for h in at.get("html"))


def ok(at):
    assert not at.exception, [e.message for e in at.exception]
    return at


# 1. the welcome popup shows in the first session only
first = ok(app())
assert welcome(first), "first visit must show the welcome"
assert store.load_prefs()["welcome_seen"] is True
second = ok(app())
assert not welcome(second), "welcome must not reopen in a later session"
second.button(key="open_welcome").click().run()
assert welcome(second), "How to use still reopens it"
print("welcome once: ok")

# 2. search results say what the ticket is, and the rest are one click away
at = ok(app())
at.text_input(key="global_search").input("orion").run()
ok(at)
labels = [b.label for b in at.sidebar.button if b.label.startswith("SUP-")]
assert labels and all(x.count(" · ") == 3 for x in labels), labels
assert any(w in x for x in labels for w in ("with L1", "with engineering", "closed"))
assert len(labels) == 8 and any(b.label.startswith("See all") for b in at.sidebar.button)
print("search shows status and all results: ok")

# 3. changed policy settings are marked, and the count is in the title
at = ok(app())
assert not any("changed" in e.label for e in at.sidebar.expander)
at.number_input(key="w_set_eng_hours").set_value(48).run()
ok(at)
assert any("Policy settings · 1 changed" in e.label for e in at.sidebar.expander), [e.label for e in at.sidebar.expander]
assert any("changed" in n.label for n in at.sidebar.number_input)
assert [b for b in at.sidebar.button if b.label == "Reset policy settings"][0].disabled is False
print("changed settings marked: ok")


# 4. account health: tier filter and a way to find any client
def page(mod, fn):
    src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui\nst.session_state.pages = {{}}\n"
           f"st.session_state.role_value = 'All views'\nfrom views import {mod}\nui.inject_css()\n{mod}.{fn}()\n")
    return ok(AppTest.from_string(src, default_timeout=180).run())


at = page("health", "account_health")
all_rows = len(at.dataframe[0].value)
at.segmented_control(key="health_tier").set_value("Enterprise").run()
ok(at)
rows = at.dataframe[0].value
assert 0 < len(rows) <= all_rows and (rows.tier == "Enterprise").all()
assert [s for s in at.selectbox if s.label == "Find any client"], "find-any-client control missing"
print("account health filters: ok")
print("phase 2 tests pass")
