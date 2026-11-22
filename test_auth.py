"""Sign-in: hashing, lockout, last-admin rule, the gate in the app, and the name on saved actions. Run: python test_auth.py"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ["RIDEOPS_STORE"] = tempfile.mkdtemp()
os.environ.pop("RIDEOPS_REQUIRE_LOGIN", None)
from sqlalchemy import select, update  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import auth  # noqa: E402
import engine as E  # noqa: E402
import store  # noqa: E402

# ---- the account system itself ----
assert not auth.required() and auth.count() == 0
admin = auth.create_user("Boss.One", "Boss One", "Admin", "a long password 1")
assert admin["username"] == "boss.one"
with store._db().connect() as c:
    stored = c.execute(select(store._users.c.pw)).scalar()
assert stored.startswith("scrypt$") and "a long password 1" not in stored, "passwords must be hashed"
for bad in (("x", "N", "Admin", "a long password 1"), ("okname", "N", "Admin", "short"), ("okname", "N", "Nope", "a long password 1"),
            ("boss.one", "N", "Admin", "a long password 1")):
    try:
        auth.create_user(*bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
assert auth.verify("boss.one", "a long password 1")["role"] == "Admin"
assert auth.verify("BOSS.ONE ", "a long password 1")["name"] == "Boss One"
assert auth.verify("boss.one", "wrong") is None and auth.verify("nobody", "x" * 12) is None
print("create and verify: ok")

# lockout: five wrong passwords lock the user, even for the right password, until the time passes
with store._db().begin() as c:                                    # earlier wrong passwords count too: start from zero
    c.execute(update(store._users).values(failed=0))
for _ in range(auth.MAX_FAILS):
    assert auth.verify("boss.one", "wrong") is None
try:
    auth.verify("boss.one", "a long password 1")
    raise AssertionError("a locked user signed in")
except PermissionError:
    pass
with store._db().begin() as c:
    c.execute(update(store._users).values(locked_until=(datetime.now() - timedelta(minutes=1)).isoformat()))
assert auth.verify("boss.one", "a long password 1")
print("lockout: ok")

# the last active administrator cannot be removed or demoted
for kwargs in ({"role": "L1 agent"}, {"active": False}):
    try:
        auth.update_user("boss.one", **kwargs)
        raise AssertionError("removed the last administrator")
    except ValueError:
        pass
auth.create_user("second", "Second Admin", "Admin", "another long pass")
auth.update_user("boss.one", role="Support lead")                # now allowed: another administrator exists
auth.update_user("second", password="brand new password")
assert auth.verify("second", "brand new password") and auth.verify("second", "another long pass") is None
print("administrators: ok")

# ---- the gate in the app ----
os.environ["RIDEOPS_REQUIRE_LOGIN"] = "1"
store.reset()                                                    # no users yet: the first visit creates the administrator
at = AppTest.from_file(HERE + "/app.py", default_timeout=180).run()
assert not at.exception, [e.message for e in at.exception]
assert [m.value for m in at.markdown][:1] == ["# RideOps Support"] and not at.sidebar.selectbox, "nothing else may render"
assert any("Create administrator" in b.label for b in at.button)
at.text_input[0].input("chief")
at.text_input[1].input("Chief Admin")
at.text_input[2].input("a long password 1")
at.text_input[3].input("a long password 1")
[b for b in at.button if "Create administrator" in b.label][0].click().run()
assert not at.exception, [e.message for e in at.exception]
assert at.session_state.user["role"] == "Admin" and "users" in at.session_state.allowed_pages
assert not [s for s in at.sidebar.selectbox if s.label == "Viewing as"], "the role is not pickable when signing in"
print("first administrator and gate: ok")

# sign out returns to the login form; a wrong password is refused without saying why
[b for b in at.sidebar.button if b.label == "Sign out"][0].click().run()
assert not at.session_state.get("user") and any(b.label == "Sign in" for b in at.button)
at.text_input[0].input("chief")
at.text_input[1].input("not the password")
[b for b in at.button if b.label == "Sign in"][0].click().run()
assert any("Wrong username or password" in e.value for e in at.error) and not at.session_state.get("user")
at.text_input[1].input("a long password 1")
[b for b in at.button if b.label == "Sign in"][0].click().run()
assert at.session_state.user["name"] == "Chief Admin"
print("sign in and out: ok")

# a signed-in person's role comes from the account and their name goes on saved actions
auth.create_user("priya", "Priya D", "L1 agent", "priya long password")
raw = E.load("data/rideops_support_tickets.csv")
t = raw[(raw.status == "Open - with L1") & (raw.escalated_to_eng == "No")].ticket_id.iloc[0]
src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, state, store\n"
       "st.session_state.user = {'username': 'priya', 'name': 'Priya D', 'role': 'L1 agent'}\n"
       f"st.session_state.role_value = 'L1 agent'\nstore.append('ticket.assign', state.actor('someone'), {{'id': '{t}', 'agent': 'Karan B'}})\n")
AppTest.from_string(src, default_timeout=60).run()
assert store.read()[-1]["by"] == "Priya D", store.read()[-1]
print("attribution: ok")
print("auth tests pass")
