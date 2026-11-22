"""Phase 3 refinements: flag labels, count formatting, tabs, gap column, terms. Run: python test_phase3.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()
from streamlit.testing.v1 import AppTest  # noqa: E402

import engine as E  # noqa: E402
import ui  # noqa: E402


def page(mod, fn, setup=""):
    src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui\nst.session_state.pages = {{}}\n"
           f"st.session_state.role_value = 'All views'\n{setup}\nfrom views import {mod}\nui.inject_css()\n{mod}.{fn}()\n")
    at = AppTest.from_string(src, default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


# 1. every flag has a short label (unique) and a full meaning
assert set(E.FLAG_SHORT) == set(E.FLAG_WEIGHTS) == set(E.FLAG_HELP)
assert len(set(E.FLAG_SHORT.values())) == len(E.FLAG_SHORT)
assert all(len(v) <= 16 for v in E.FLAG_SHORT.values()), "short labels must stay short"
print("flag labels: ok")

# 2. counts are whole numbers, rates and averages keep their decimals
assert E.fmt_metric("Tickets", 1444.0) == "1,444" and E.fmt_metric("Duplicate escalations", 56.0) == "56"
assert E.fmt_metric("CSAT (avg)", 3.66) == "3.7" and E.fmt_metric("Reopen rate", 0.103) == "10.3%"
print("count formatting: ok")

# 3. the 1:1 button on the coaching page switches to the 1:1 tab
at = page("support", "agent_coaching")
assert [t.label for t in at.tabs] == ["Team overview", "1:1 prep"]
[b for b in at.button if b.label == "1:1 prep"][0].click().run()
assert not at.exception, [e.message for e in at.exception]
assert at.session_state.coaching_tabs == "1:1 prep"
assert any(m.value == "# Agent 1:1 prep" for m in at.markdown), [m.value for m in at.markdown][:6]
print("coaching tabs: ok")

# 4. root causes has one tab per owner
at = page("engineering", "root_causes")
assert [t.label for t in at.tabs] == ["Engineering: recurring issues", "Product: feature requests",
                                      "Operations: cab delays and no-shows"]
print("root causes tabs: ok")

# 5. the targets table has a gap column
at = page("overview", "scorecard")
assert any("Gap" in str(h.value) for h in at.get("html"))
print("targets gap: ok")

# 6. every page header offers the terms list
assert len(ui.TERMS) >= 8 and all(t and m for t, m in ui.TERMS)
print("terms: ok")
print("phase 3 tests pass")
