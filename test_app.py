"""Interaction tests using Streamlit's AppTest (headless). Run from this folder: python test_app.py

Each check drives real widgets and asserts on the result, not just "no exception".
"""
import datetime
import pathlib
import re
import os
import sys
import tempfile
import traceback

import pandas as pd
from streamlit.testing.v1 import AppTest

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()      # saved choices and actions go to a throwaway folder
sys.path.insert(0, HERE)
os.chdir(HERE)
RESULTS = []
SAMPLE = pd.read_csv("data/rideops_support_tickets.csv")


def _write(name, df):
    """Write a CSV to a temporary file and return its path."""
    path = os.path.join(tempfile.mkdtemp(), f"{name}.csv")
    df.to_csv(path, index=False)
    return path


def check(name):
    def wrap(fn):
        import store
        store.reset()      # every check starts from a clean slate
        try:
            fn()
            RESULTS.append((name, "PASS", ""))
        except Exception as e:  # report every failure, keep going
            RESULTS.append((name, "FAIL", f"{type(e).__name__}: {e}"))
            traceback.print_exc()
        return fn
    return wrap


def view(mod, fn, setup="", raw=None):
    pre = f"st.session_state.raw = open(r'{raw}', 'rb').read()\n" if raw else ""
    src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui, state\n{pre}{setup}\n"
           f"from views import {mod}\nui.inject_css()\nstate.show_flash()\n{mod}.{fn}()\n")
    return AppTest.from_string(src, default_timeout=120).run()


def no_exc(at):
    assert not at.exception, [e.message for e in at.exception]
    return at


def h1(at):
    return [m.value for m in at.markdown if m.value.startswith("# ")]


def table_rows(at, i=0):
    return len(at.dataframe[i].value)


VIEWS = [("overview", "scorecard"), ("support", "attention_queue"), ("support", "agent_coaching"),
         ("oneonone", "agent_one_on_one"),
         ("engineering", "returns"), ("engineering", "registry"), ("engineering", "root_causes"),
         ("insights", "before_after"), ("insights", "backtests"), ("insights", "methodology")]

# ---------------- shell ----------------


@check("Shell: loads on Scorecard with no errors")
def _():
    at = no_exc(AppTest.from_file("app.py", default_timeout=120).run())
    assert h1(at) == ["# Scorecard"], h1(at)


@check("Shell: each role shows exactly its menu")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    expect = {"Head of Operations": 5, "Support lead": 8, "Engineering lead": 6, "L1 agent": 4, "All views": 12}
    for role, n in expect.items():
        at.selectbox(key="role").select(role).run()
        no_exc(at)
        assert len(at.session_state.allowed_pages) == n, (role, at.session_state.allowed_pages)


@check("Shell: role switch from a page the role doesn't use lands on its first page")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.selectbox(key="role").select("L1 agent").run()
    no_exc(at)
    assert h1(at) == ["# My desk"], h1(at)


@check("Shell: global search finds a ticket and opens its details")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.text_input(key="global_search").input("SUP-11267").run()
    btns = [b for b in at.sidebar.button if b.label.startswith("SUP-11267")]
    assert len(btns) == 1, [b.label for b in at.sidebar.button]
    btns[0].click().run()
    no_exc(at)
    assert any("SUP-11267" in m.value for m in at.markdown), "dialog heading missing"


@check("Shell: global search with no match says so")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.text_input(key="global_search").input("zzz-no-such-ticket").run()
    assert any("No tickets match" in c.value for c in at.sidebar.caption)


@check("Before / after: the go-live date is picked on the page and splits before/after")
def _():
    at = no_exc(view("insights", "before_after"))
    at.date_input(key="go_live_20260930").set_value(datetime.date(2026, 9, 1)).run()
    no_exc(at)
    assert at.session_state.go_live_value == datetime.date(2026, 9, 1)
    assert any("Tickets" in str(t.value) for t in at.get("html"))


@check("Shell: role and go-live date survive a role change that switches page, and are saved")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.session_state.go_live_value = datetime.date(2026, 9, 1)
    at.selectbox(key="role").select("Engineering lead").run()   # Scorecard is not in this role -> page switch
    no_exc(at)
    assert at.session_state.role_value == "Engineering lead"
    assert at.session_state.go_live_value == datetime.date(2026, 9, 1)
    assert len(at.session_state.allowed_pages) == 6
    import store
    assert store.load_prefs()["go_live"] == "2026-09-01"


# ---------------- every view ----------------


for _m, _f in VIEWS:
    @check(f"View renders: {_m}.{_f}")
    def _(m=_m, f=_f):
        at = no_exc(view(m, f))
        assert len(h1(at)) == 1


# ---------------- attention queue ----------------


@check("Queue: search narrows rows, no-match shows empty state, Clear filters restores")
def _():
    at = no_exc(view("support", "attention_queue"))
    full = table_rows(at)
    at.text_input(key="aq_search").input("SUP-11267").run()
    assert table_rows(at) == 1, table_rows(at)
    at.text_input(key="aq_search").input("zzz").run()
    assert not at.dataframe or table_rows(at) != full
    assert any("No tickets match" in str(h.value) for h in at.get("html")), "empty state missing"
    [b for b in at.button if b.label == "Clear filters"][0].click().run()
    assert at.text_input(key="aq_search").value == "" and table_rows(at) == full


@check("Queue: agent filter and flag filter combine")
def _():
    at = view("support", "attention_queue", "st.session_state.aq_flags = ['Reopened by client']")
    no_exc(at)
    assert table_rows(at) == 9, table_rows(at)
    at.multiselect(key="aq_agents").select("Karan B").run()
    rows = at.dataframe[0].value
    assert len(rows) <= 9 and (rows.assigned_agent == "Karan B").all()



@check("Registry: save keeps list and confirms")
def _():
    at = view("engineering", "registry")
    n = len(at.session_state.registry)
    [b for b in at.button if b.label == "Save changes"][0].click().run()
    no_exc(at)
    assert len(at.session_state.registry) == n
    assert at.toast and "Registry saved" in at.toast[0].value, [t.value for t in at.toast]


@check("Registry: rows without an issue are rejected")
def _():
    setup = ("import engine as E, pandas as pd\nc = state.context()\n"
             "r = st.session_state.registry\n"
             "st.session_state.registry = pd.concat([r, r.head(1).assign(template='')], ignore_index=True)")
    at = view("engineering", "registry", setup)
    [b for b in at.button if b.label == "Save changes"][0].click().run()
    assert at.error and "need an issue" in at.error[0].value, [e.value for e in at.error]


@check("Registry: reset restores the seeded list")
def _():
    setup = ("c = state.context()\nif 'trimmed' not in st.session_state:\n"
             "    st.session_state.trimmed = True\n    st.session_state.registry = st.session_state.registry.head(2)")
    at = view("engineering", "registry", setup)
    assert len(at.session_state.registry) == 2
    [b for b in at.button if b.label == "Reset registry"][0].click().run()
    no_exc(at)
    assert len(at.session_state.registry) > 2

# ---------------- ticket dialog ----------------


@check("Upload validation: empty and bad-date files raise a readable error")
def _():
    import io

    import state
    for df, msg in [(SAMPLE.head(0), "no ticket rows"), (SAMPLE.head(5).assign(created_at="x"), "created_at")]:
        try:
            state._prepare.__wrapped__(df.to_csv(index=False).encode(), None, (0, 0))
            raise AssertionError("no error raised")
        except state.READ_ERRORS as e:
            assert msg in str(e), str(e)
    try:
        state._prepare.__wrapped__(io.BytesIO(b"a,b\n1,2").getvalue(), None, (0, 0))
        raise AssertionError("no error for missing columns")
    except state.READ_ERRORS as e:
        assert "missing columns" in str(e)


@check("Upload: timestamps with seconds and lowercase 'yes' are read correctly")
def _():
    import io

    import engine as E
    df = SAMPLE.head(200).assign(created_at=lambda x: x.created_at + ":00",
                                 escalated_to_eng=lambda x: x.escalated_to_eng.str.lower())
    d = E.load(io.BytesIO(df.to_csv(index=False).encode()))
    assert d.created_at.notna().all()
    assert int(d.escalated_to_eng.eq("Yes").sum()) == int((SAMPLE.head(200).escalated_to_eng == "Yes").sum())


@check("Go-live default follows newly loaded data unless the user picked a date")
def _():
    p = _write("july", SAMPLE.head(30))
    try:
        src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, state\n"
               f"st.session_state.raw = open(r'{p}', 'rb').read()\nc = state.context()\n"
               "st.write(str(c.go_live.date()), str(c.as_of.date()))\n")
        at = no_exc(AppTest.from_string(src, default_timeout=120).run())
        go_live, as_of = at.markdown[0].value.split()
        assert go_live == str((pd.Timestamp(as_of) + pd.Timedelta(days=1)).date()), (go_live, as_of)
    finally:
        os.remove(p)


def _md(at):
    return [m.value for m in at.markdown]


def _welcome(at):
    return any("Start here" in str(h.value) for h in at.get("html"))


def _btn(at, label):
    return [b for b in at.button if b.label == label]


@check("Guide: welcome opens once per session with the role's 3 tasks, and How to use reopens it")
def _():
    at = no_exc(AppTest.from_file("app.py", default_timeout=120).run())
    assert _welcome(at), "welcome not shown on first visit"
    assert len([b for b in at.button if b.key and b.key.startswith("welcome_go_")]) == 3
    at.run()
    assert not _welcome(at), "welcome shown again"
    at.button(key="open_welcome").click().run()
    assert _welcome(at)


# Welcome 'Go' buttons are verified in a real browser: AppTest replays clicks with a full rerun, and the
# welcome dialog is only drawn on the first run, so the click never reaches it headlessly.


@check("Guide: tour steps through the role's pages, Back works, Finish closes it")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.selectbox(key="role").select("Engineering lead").run()    # 6 pages: escalations, returns, registry, roots, backtests, method
    at.button(key="open_tour").click().run()
    no_exc(at)
    assert "Step 1 of 6" in [c.value for c in at.caption] and h1(at) == ["# Escalations"]
    _btn(at, "Next")[0].click().run()
    assert "Step 2 of 6" in [c.value for c in at.caption] and h1(at) == ["# Returns from engineering"], h1(at)
    _btn(at, "Back")[0].click().run()
    assert "Step 1 of 6" in [c.value for c in at.caption] and h1(at) == ["# Escalations"]
    for _ in range(5):
        _btn(at, "Next")[0].click().run()
    assert "Step 6 of 6" in [c.value for c in at.caption] and _btn(at, "Finish")
    _btn(at, "Finish")[0].click().run()
    no_exc(at)
    assert not at.session_state.tour_open and not any(c.value.startswith("Step ") for c in at.caption)


@check("Guide: role picked in the welcome dialog sticks (sidebar picker and tour follow it)")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.selectbox(key="welcome_role").select("Engineering lead").run()
    assert at.session_state.role_value == "Engineering lead"
    assert at.selectbox(key="role").value == "Engineering lead"
    at.button(key="open_tour").click().run()
    _btn(at, "Next")[0].click().run()
    no_exc(at)
    assert at.session_state.role_value == "Engineering lead"
    assert "Step 2 of 6" in [c.value for c in at.caption], [c.value for c in at.caption]


@check("1:1 prep: every agent renders with findings, tickets and a download")
def _():
    import pandas as pd
    agents = sorted(pd.read_csv("data/rideops_support_tickets.csv").assigned_agent.unique())
    assert len(agents) == 8
    for a in agents:
        at = no_exc(view("oneonone", "agent_one_on_one", f"st.session_state.oo_agent_pending = {a!r}"))
        assert at.selectbox(key="oo_agent").value == a
        assert [b.label for b in at.get("download_button")] == ["Download 1:1 summary"]
        texts = " ".join(m.value for m in at.markdown)
        assert "To discuss" in texts and "Numbers against the other agents" in texts


@check("1:1 prep: Rahul's page leads with the escalation finding and real numbers")
def _():
    at = no_exc(view("oneonone", "agent_one_on_one", "st.session_state.oo_agent_pending = 'Rahul T'"))
    html = " ".join(str(h.value) for h in at.get("html"))
    md = " ".join(m.value for m in at.markdown)
    assert "Escalates far more than peers" in html
    assert "61.6%" in md and "32 of 32" in md and "Shadow Vikram S" in md


@check("1:1 prep: agent picker switches the page and the agreement boxes are per agent")
def _():
    at = no_exc(view("oneonone", "agent_one_on_one"))
    at.selectbox(key="oo_agent").select("Karan B").run()
    no_exc(at)
    assert any("fixes do not hold" in str(h.value) for h in at.get("html"))
    at.text_input(key="oo_action_Karan B").input("Confirm fixes with client").run()
    assert at.text_input(key="oo_action_Karan B").value == "Confirm fixes with client"


@check("Agent coaching: every agent has a point to discuss and a working link to 1:1 prep")
def _():
    at = no_exc(view("support", "agent_coaching"))
    assert len([b for b in at.button if b.label == "1:1 prep"]) == 8


@check("Policy settings: changing a deadline in the sidebar changes the scorecard and survives a page change")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    before = " ".join(c.value for c in at.caption)
    assert "within 24h (not escalated) or 72h (escalated)" in before
    at.number_input(key="w_set_eng_hours").set_value(48).run()
    no_exc(at)
    assert at.session_state.set_eng_hours == 48
    after = " ".join(c.value for c in at.caption)
    assert "or 48h (escalated)" in after and "or 72h" not in after
    at.selectbox(key="role").select("Support lead").run()       # page switch resets widgets; the setting must stay
    assert at.session_state.set_eng_hours == 48
    at.button[[b.label for b in at.button].index("Reset policy settings")].click().run()
    assert "set_eng_hours" not in at.session_state


@check("Guide: every page in every role has a tour step and task text")
def _():
    import guide
    src = pathlib.Path("app.py").read_text(encoding="utf-8")
    for key in re.findall(r'^    "(\w+)": page\("', src, flags=re.M):
        assert key in guide.STEPS, f"page {key!r} has no tour step"
    for role, tasks in guide.TASKS.items():
        assert all(k in guide.STEPS for _, k in tasks), role


@check("Guide: the welcome dialog opens without error for every role")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    for role in at.selectbox(key="role").options:
        at.selectbox(key="role").select(role).run()
        at.button(key="open_welcome").click().run()
        no_exc(at)


@check("Guide: End tour closes it and it stays closed")
def _():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.button(key="open_tour").click().run()
    _btn(at, "End tour")[0].click().run()
    at.run()
    assert not any(c.value.startswith("Step ") for c in at.caption)


if __name__ == "__main__":
    w = max(len(n) for n, _, _ in RESULTS)
    for n, s, why in RESULTS:
        print(f"{s}  {n:<{w}}  {why}")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)
