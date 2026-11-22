"""Optional sign-in: users with a role, stored in the database. Off by default; set RIDEOPS_REQUIRE_LOGIN=1 to turn it on
(do this before hosting the app anywhere other people can reach).

- Passwords are never stored: only a salted scrypt hash.
- Five wrong passwords lock that user for five minutes. The message never says whether the user exists.
- The role decides the menu and the lead-only buttons, and every saved action carries the person's name.
- The first person to open a fresh app creates the administrator. Administrators add the rest on the Users page.

Limits: a sign-in lasts as long as the browser tab's session (a refresh signs you out); there is no password reset by
email, an administrator sets a new password; this is a small built-in system, not single sign-on.
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select, update

import store

ROLES = ["Admin", "All views", "Head of Operations", "Support lead", "Engineering lead", "L1 agent"]
MIN_PASSWORD = 10
MAX_FAILS = 5
LOCK_MINUTES = 5
_NAME = re.compile(r"^[a-z0-9._-]{3,40}$")
_DUMMY = "scrypt$" + "00" * 16 + "$" + "00" * 32          # compared against when the user does not exist, to even out timing


def required() -> bool:
    return os.environ.get("RIDEOPS_REQUIRE_LOGIN", "").strip().lower() in ("1", "true", "yes")


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _check(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        return hmac.compare_digest(_hash(password, bytes.fromhex(salt)).split("$")[2], digest)
    except ValueError:
        return False


def _db():
    return store._db()


def _now() -> datetime:
    return datetime.now()


def count() -> int:
    with _db().connect() as c:
        return int(c.execute(select(func.count()).select_from(store._users)).scalar())


def _validate(username: str, name: str, role: str) -> str:
    if not _NAME.match(username):
        return "The username is 3 to 40 characters: letters, digits, dot, dash or underscore."
    if not name.strip() or len(name.strip()) > 60:
        return "Enter the person's name (up to 60 characters)."
    if role not in ROLES:
        return "Unknown role."
    return ""


def check_password(password: str) -> str:
    return "" if len(password) >= MIN_PASSWORD else f"The password needs at least {MIN_PASSWORD} characters."


def create_user(username: str, name: str, role: str, password: str) -> dict:
    username = username.strip().lower()
    err = _validate(username, name, role) or check_password(password)
    if err:
        raise ValueError(err)
    with _db().begin() as c:
        if c.execute(select(store._users.c.username).where(store._users.c.username == username)).first():
            raise ValueError("That username is taken.")
        c.execute(insert(store._users).values(username=username, name=name.strip(), role=role, pw=_hash(password), active=1,
                                              failed=0, locked_until="", created_at=_now().isoformat(timespec="minutes")))
    return {"username": username, "name": name.strip(), "role": role}


def verify(username: str, password: str) -> dict | None:
    """The user dict when the password is right, None when it is wrong. Raises PermissionError while locked."""
    username = username.strip().lower()
    with _db().begin() as c:
        row = c.execute(select(store._users).where(store._users.c.username == username)).mappings().first()
        if not row:
            _check(password, _DUMMY)
            return None
        if row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > _now():
            raise PermissionError(f"Too many wrong passwords. Try again in {LOCK_MINUTES} minutes.")
        if row["active"] and _check(password, row["pw"]):
            c.execute(update(store._users).where(store._users.c.username == username).values(failed=0, locked_until=""))
            return {"username": username, "name": row["name"], "role": row["role"]}
        failed = int(row["failed"] or 0) + 1
        lock = (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat() if failed >= MAX_FAILS else ""
        c.execute(update(store._users).where(store._users.c.username == username)
                  .values(failed=0 if lock else failed, locked_until=lock))
    return None


def list_users() -> list:
    with _db().connect() as c:
        rows = c.execute(select(store._users.c.username, store._users.c.name, store._users.c.role, store._users.c.active,
                                store._users.c.created_at).order_by(store._users.c.username)).mappings().all()
    return [dict(r) for r in rows]


def _active_admins(exclude: str = "") -> int:
    with _db().connect() as c:
        return int(c.execute(select(func.count()).select_from(store._users).where(
            store._users.c.role == "Admin", store._users.c.active == 1, store._users.c.username != exclude)).scalar())


def update_user(username: str, *, role: str | None = None, active: bool | None = None, password: str | None = None) -> None:
    """Change a user's role, active flag or password. The last active administrator cannot be removed."""
    vals = {}
    if role is not None:
        if role not in ROLES:
            raise ValueError("Unknown role.")
        vals["role"] = role
    if active is not None:
        vals["active"] = int(active)
    if password is not None:
        err = check_password(password)
        if err:
            raise ValueError(err)
        vals["pw"] = _hash(password)
        vals["failed"], vals["locked_until"] = 0, ""
    if (vals.get("role", "Admin") != "Admin" or vals.get("active", 1) == 0) and _active_admins(exclude=username) == 0:
        with _db().connect() as c:
            cur = c.execute(select(store._users.c.role, store._users.c.active).where(store._users.c.username == username)).first()
        if cur and cur[0] == "Admin" and cur[1] == 1:
            raise ValueError("There must be at least one active administrator.")
    if vals:
        with _db().begin() as c:
            c.execute(update(store._users).where(store._users.c.username == username).values(**vals))
