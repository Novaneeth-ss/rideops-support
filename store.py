"""Everything the app saves, in a database, replayed on top of the ticket export.

Where: SQLite by default (a file, `rideops.db`, in the folder named by RIDEOPS_STORE or `store/`). Set DATABASE_URL to use
PostgreSQL (or any SQLAlchemy URL) instead, which is what a host with a temporary disk needs. Nothing else is written.

What is saved:
- datasets: every uploaded or API-fetched export, and which one is active;
- events: an append-only log of actions (escalations, returns, reassignments, ...), per dataset;
- kv: preferences (global) and per-dataset values (known-issue registry, 1:1 agreements, API connection).

Why events: the export has no record of when a ticket entered or left engineering, what the agent noted when escalating,
or which checks were done. Those are recorded here from the first action onward. Nothing is back-filled.
Times are real wall-clock times. The export's own clock stops at its last ticket, so the two are kept apart.
"""
import copy
import json
import os
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from sqlalchemy import Column, Integer, LargeBinary, MetaData, String, Table, Text, create_engine, delete, func, insert, select

SAMPLE = "sample"          # dataset key used while no upload is active

RETURN_REASONS = ["Config issue - returned to L1", "Insufficient info - returned to L1", "Not a bug - how-to",
                  "Not reproducible", "Duplicate of known issue"]
MIN_NOTE_CHARS = 20        # a "detailed note" is at least this long (the escalation gate asks for the same)
# type -> required fields
TYPES = {
    "ticket.escalate": ["id", "note", "checks_done", "checks_total"],
    "ticket.return": ["id", "reason"],
    "ticket.fixed": ["id"],
    "ticket.call_required": ["id"],
    "ticket.eng_head": ["id", "note"],
    "ticket.lag_mark": ["id"],
    "ticket.assign": ["id", "agent"],
    "feature.status": ["key", "status"],
    "config.eng_sla": ["hours"],
    "ticket.call_held": ["id", "who"],
    "ticket.known_issue": ["id", "issue"],
    "event.undo": ["event_id"],
    "account.called": ["client", "note"],
}
# the latest of these on a ticket can be taken back (config and feature statuses are not tied to one ticket)
UNDOABLE = {"ticket.escalate", "ticket.return", "ticket.fixed", "ticket.call_required", "ticket.call_held",
            "ticket.eng_head", "ticket.lag_mark", "ticket.assign", "ticket.known_issue", "account.called"}
NEW_COLS = {"eng_entered_at": pd.NaT, "eng_left_at": pd.NaT, "eng_done_h": 0.0, "esc_note": "", "checks_done": float("nan"),
            "checks_total": float("nan"), "call_required_ev": False, "lag_marked": False, "eng_head_at": pd.NaT,
            "eng_head_note": "", "tracked": False, "call_held_at": pd.NaT, "call_held_with": "", "known_issue": ""}

# ---------------- database ----------------
_meta = MetaData()
_events = Table("events", _meta, Column("id", Integer, primary_key=True, autoincrement=True), Column("ds", String(40), index=True),
                Column("at", String(32)), Column("type", String(40)), Column("by", String(80)), Column("data", Text))
_kv = Table("kv", _meta, Column("ds", String(40), primary_key=True), Column("k", String(120), primary_key=True), Column("v", Text))
_datasets = Table("datasets", _meta, Column("id", Integer, primary_key=True, autoincrement=True), Column("name", String(255)),
                  Column("source", String(20)), Column("uploaded_at", String(32)), Column("content", LargeBinary))


_users = Table("users", _meta, Column("username", String(60), primary_key=True), Column("name", String(80)),
               Column("role", String(40)), Column("pw", String(300)), Column("active", Integer), Column("failed", Integer),
               Column("locked_until", String(32)), Column("created_at", String(32)))


def _require_tls(url: str) -> str:
    """A remote PostgreSQL connection is encrypted unless the URL says otherwise. Without sslmode, the driver may quietly fall
    back to plain text. Local databases (localhost or a socket path) are left alone."""
    parts = urlsplit(url)
    if not parts.scheme.startswith("postgres") or parts.hostname in (None, "localhost", "127.0.0.1", "::1"):
        return url
    if "sslmode=" in parts.query or "host=" in parts.query:
        return url
    return urlunsplit(parts._replace(query=(parts.query + "&" if parts.query else "") + "sslmode=require"))


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):            # some hosts still hand out the old scheme
        url = "postgresql://" + url[len("postgres://"):]
    if url:
        return _require_tls(url)
    folder = Path(os.environ.get("RIDEOPS_STORE") or Path(__file__).parent / "store")
    folder.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(folder / 'rideops.db').as_posix()}"


@lru_cache(maxsize=4)
def _engine(url: str):
    eng = create_engine(url, pool_pre_ping=True)
    _meta.create_all(eng)
    return eng


# Reads are remembered for a few seconds. One page run asks the same questions many times (which dataset, which actions, which
# preferences); against a hosted database each ask costs a network round trip, so a page took seconds. Every write in this
# process forgets everything at once; another server process sees a change within MEMO_SECONDS.
MEMO_SECONDS = 4.0
_memo: dict = {}
_memo_lock = threading.Lock()


def _forget() -> None:
    with _memo_lock:
        _memo.clear()


def _remembered(fn):
    def wrapper(*args, **kwargs):
        key = (database_url(), fn.__name__, repr(args), repr(sorted(kwargs.items())))      # a default such as {} is not hashable
        now = time.monotonic()
        with _memo_lock:
            hit = _memo.get(key)
        if hit and now - hit[0] < MEMO_SECONDS:
            return copy.deepcopy(hit[1]) if fn.__name__ == "kv_get" else hit[1]
        val = fn(*args, **kwargs)
        with _memo_lock:
            _memo[key] = (now, val)
        return copy.deepcopy(val) if fn.__name__ == "kv_get" else val
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


_engine_lock = threading.Lock()


def _db():
    # Streamlit runs each visitor's session in its own thread; two first requests creating the tables at once fail
    with _engine_lock:
        return _engine(database_url())


def reset() -> None:
    """Delete everything saved (tests, or a deliberate fresh start)."""
    with _db().begin() as c:
        for t in (_events, _kv, _datasets, _users):
            c.execute(delete(t))
    _forget()


# ---------------- key-value ----------------
@_remembered
def kv_get(key: str, default=None, ds: str | None = ""):
    """ds="" = global; ds=None = the active dataset."""
    ds = active_key() if ds is None else ds
    with _db().connect() as c:
        v = c.execute(select(_kv.c.v).where(_kv.c.ds == ds, _kv.c.k == key)).scalar()
    try:
        return default if v is None else json.loads(v)
    except ValueError:
        return default


def kv_set(key: str, value, ds: str | None = "") -> None:
    ds = active_key() if ds is None else ds
    with _db().begin() as c:
        c.execute(delete(_kv).where(_kv.c.ds == ds, _kv.c.k == key))
        if value is not None:
            c.execute(insert(_kv).values(ds=ds, k=key, v=json.dumps(value)))
    _forget()


def load_prefs() -> dict:
    """Role, policy settings and go-live date chosen last time. There are no logins, so these are shared by everyone."""
    return kv_get("prefs", {}) or {}


def save_prefs(prefs: dict) -> None:
    kv_set("prefs", prefs)


# ---------------- saved reply templates (macros) ----------------
MACRO_KINDS = ("reply", "close")
MACRO_PLACEHOLDERS = ("{client}", "{ticket}", "{issue}", "{category}", "{agent}")
MACRO_NAME_MAX, MACRO_BODY_MAX, MACRO_LIMIT = 60, 2000, 20     # per person and kind


def macros(owner: str, kind: str | None = None) -> list:
    """The templates this person saved: [{kind, name, body}], optionally for one kind."""
    rows = kv_get(f"macros:{owner}", []) or []
    return [m for m in rows if kind is None or m.get("kind") == kind]


def save_macro(owner: str, kind: str, name: str, body: str) -> str | None:
    """Save (or replace, by name) a template. Returns the reason it was refused, or None when saved."""
    name, body = (name or "").strip(), (body or "").strip()
    if kind not in MACRO_KINDS:
        return "Unknown template type."
    if not name or not body:
        return "Give the template a name and some text."
    if len(name) > MACRO_NAME_MAX or len(body) > MACRO_BODY_MAX:
        return f"Keep the name under {MACRO_NAME_MAX} characters and the text under {MACRO_BODY_MAX}."
    rows = macros(owner)
    kept = [m for m in rows if not (m["kind"] == kind and m["name"].lower() == name.lower())]
    if len([m for m in kept if m["kind"] == kind]) >= MACRO_LIMIT:
        return f"You can keep up to {MACRO_LIMIT} templates of each type. Delete one first."
    kv_set(f"macros:{owner}", kept + [{"kind": kind, "name": name, "body": body}])
    return None


def delete_macro(owner: str, kind: str, name: str) -> None:
    kv_set(f"macros:{owner}", [m for m in macros(owner) if not (m["kind"] == kind and m["name"] == name)] or None)


def fill_macro(body: str, values: dict) -> str:
    """Put the ticket's details into a template. Unknown {words} are left as typed."""
    for k, v in values.items():
        body = body.replace("{" + k + "}", str(v))
    return body


def load_registry() -> pd.DataFrame | None:
    """The known-issue registry of the active dataset as last saved, or None when nobody has saved one."""
    rows = kv_get("registry", None, ds=None)
    if rows is None:
        return None
    df = pd.DataFrame(rows)
    if "last_seen" in df:
        df["last_seen"] = pd.to_datetime(df.last_seen, errors="coerce")
    return df


def save_registry(df: pd.DataFrame | None) -> None:
    """Save the registry (None removes the saved copy, so the next start re-seeds it from the data)."""
    kv_set("registry", None if df is None else json.loads(df.to_json(orient="records", date_format="iso")), ds=None)


# ---------------- datasets ----------------
def active_key() -> str:
    """Which dataset is in use: an uploaded or fetched one (by id) or the bundled sample."""
    return str(kv_get("active_dataset", None) or SAMPLE)


def save_dataset(name: str, content: bytes, source: str = "upload") -> int:
    """Save an export and make it the active dataset for everyone using this server."""
    with _db().begin() as c:
        new_id = c.execute(insert(_datasets).values(name=name[:255], source=source, content=content,
                                                    uploaded_at=now().isoformat(timespec="minutes"))).inserted_primary_key[0]
    kv_set("active_dataset", int(new_id))
    _forget()
    return int(new_id)


def set_active(dataset_id: int | None) -> None:
    kv_set("active_dataset", dataset_id)


@_remembered
def active_dataset() -> dict | None:
    """The active saved dataset (id, name, source, uploaded_at; the content is dataset_content), or None for the sample."""
    key = active_key()
    if key == SAMPLE:
        return None
    with _db().connect() as c:
        r = c.execute(select(_datasets.c.id, _datasets.c.name, _datasets.c.source, _datasets.c.uploaded_at)
                      .where(_datasets.c.id == int(key))).mappings().first()
    return dict(r) if r else None


def dataset_content(dataset_id: int) -> bytes | None:
    with _db().connect() as c:
        return c.execute(select(_datasets.c.content).where(_datasets.c.id == int(dataset_id))).scalar()


@_remembered
def list_datasets() -> list:
    with _db().connect() as c:
        rows = c.execute(select(_datasets.c.id, _datasets.c.name, _datasets.c.source, _datasets.c.uploaded_at)
                         .order_by(_datasets.c.id.desc())).mappings().all()
    return [dict(r) for r in rows]


# ---------------- events ----------------
def now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def validate(e: dict) -> str:
    if e.get("type") not in TYPES:
        return f"unknown event type: {e.get('type')}"
    if not isinstance(e.get("by"), str) or not e["by"] or len(e["by"]) > 60:
        return "by must be a short name"
    d = e.get("data")
    if not isinstance(d, dict):
        return "data must be an object"
    miss = [k for k in TYPES[e["type"]] if d.get(k) is None or (k not in ("note",) and d.get(k) == "")]
    if miss:
        return "missing: " + ", ".join(miss)
    if e["type"] == "ticket.return" and d["reason"] not in RETURN_REASONS:
        return "unknown return reason"
    if e["type"] == "event.undo" and not isinstance(d["event_id"], int):
        return "event_id must be a number"
    if e["type"] == "config.eng_sla" and not (isinstance(d["hours"], (int, float)) and d["hours"] > 0):
        return "hours must be a positive number"
    return ""


@_remembered
def read(ds: str | None = None) -> list:
    """Saved actions of a dataset (default: the active one), oldest first, with each one's id. Actions that were taken
    back (undone) are left out, and so are the undo records themselves. Damaged rows are skipped."""
    ds = ds or active_key()
    with _db().connect() as c:
        rows = c.execute(select(_events).where(_events.c.ds == ds).order_by(_events.c.id)).mappings().all()
    out = []
    for r in rows:
        try:
            e = {"id": int(r["id"]), "at": r["at"], "type": r["type"], "by": r["by"], "data": json.loads(r["data"])}
        except ValueError:
            continue
        if not validate(e):
            out.append(e)
    voided = {e["data"]["event_id"] for e in out if e["type"] == "event.undo"}
    return [e for e in out if e["type"] != "event.undo" and e["id"] not in voided]


def last_for_ticket(events: list, ticket_id: str) -> dict | None:
    """The most recent action on a ticket that can be undone, or None. Only the latest can be taken back, so the
    ticket's history never ends up in a state nobody did."""
    mine = [e for e in events if e["data"].get("id") == ticket_id and e["type"].startswith("ticket.")]
    return mine[-1] if mine and mine[-1]["type"] in UNDOABLE else None


def last_call(events: list, client: str) -> dict | None:
    """The latest recorded call to a client (account health), or None."""
    mine = [e for e in events if e["type"] == "account.called" and e["data"]["client"] == client]
    return mine[-1] if mine else None


def undo(event_id: int, by: str) -> dict:
    """Take back one saved action. The action stays in the database with a record of who undid it."""
    return append("event.undo", by, {"event_id": int(event_id)})


@_remembered
def signature(ds: str | None = None) -> tuple:
    """Changes whenever the active dataset or its actions change; used to refresh cached data."""
    ds = ds or active_key()
    with _db().connect() as c:
        n, last = c.execute(select(func.count(_events.c.id), func.coalesce(func.max(_events.c.id), 0))
                            .where(_events.c.ds == ds)).one()
    return (ds, int(n), int(last))


def append(type_: str, by: str, data: dict, ds: str | None = None) -> dict:
    e = {"at": now().isoformat(timespec="minutes"), "type": type_, "by": by, "data": data}
    err = validate(e)
    if err:
        raise ValueError(err)
    with _db().begin() as c:
        c.execute(insert(_events).values(ds=ds or active_key(), at=e["at"], type=type_, by=by, data=json.dumps(data)))
    _forget()
    return e


def sla_override(events: list) -> int | None:
    """The latest saved engineering SLA (hours), or None when nobody set one."""
    hrs = [e["data"]["hours"] for e in events if e["type"] == "config.eng_sla"]
    return int(round(hrs[-1])) if hrs else None


def feature_status(events: list) -> dict:
    return {e["data"]["key"]: e["data"]["status"] for e in events if e["type"] == "feature.status"}


def apply(df: pd.DataFrame, events: list) -> pd.DataFrame:
    """Replay the log on the raw export. Unknown tickets are ignored. Returns a new frame with tracking columns."""
    d = df.copy()
    for c, v in NEW_COLS.items():
        d[c] = v
    d["eng_entered_at"] = pd.to_datetime(d.eng_entered_at)
    d["eng_left_at"] = pd.to_datetime(d.eng_left_at)
    d["eng_head_at"] = pd.to_datetime(d.eng_head_at)
    d["esc_note"] = d.esc_note.astype(object)
    d["eng_head_note"] = d.eng_head_note.astype(object)
    idx = {t: i for i, t in zip(d.index, d.ticket_id)}
    eng_n = pd.to_numeric(d.eng_ticket_id.dropna().astype(str).str.extract(r"(\d+)")[0], errors="coerce").max()
    eng_n = 0 if pd.isna(eng_n) else int(eng_n)
    for e in events:
        t = e["data"].get("id")
        i = idx.get(t)
        if e["type"].startswith("ticket.") and i is None:
            continue
        at = pd.Timestamp(e["at"])
        row = d.loc[i] if i is not None else None
        op = d.at
        if e["type"] == "ticket.escalate":
            if pd.notna(row.final_closed_at):
                continue                                           # a closed ticket cannot be escalated
            if pd.isna(row.eng_ticket_id) or not str(row.eng_ticket_id).strip():
                eng_n += 1
                op[i, "eng_ticket_id"] = f"ENG-{eng_n}"
            op[i, "escalated_to_eng"] = "Yes"
            op[i, "eng_handoffs"] = row.eng_handoffs + 1
            op[i, "eng_outcome"] = None
            op[i, "status"] = "Open - with Engineering"
            op[i, "eng_entered_at"], op[i, "eng_left_at"] = at, pd.NaT
            op[i, "esc_note"] = e["data"]["note"]
            op[i, "checks_done"], op[i, "checks_total"] = e["data"]["checks_done"], e["data"]["checks_total"]
            op[i, "tracked"] = True
        elif e["type"] in ("ticket.return", "ticket.fixed"):
            if row.status != "Open - with Engineering":
                continue
            if e["type"] == "ticket.return" and row.eng_handoffs >= 2:
                op[i, "call_required_ev"] = True                  # a 2nd escalation cannot be bounced back
                continue
            op[i, "eng_outcome"] = "Fixed" if e["type"] == "ticket.fixed" else e["data"]["reason"]
            op[i, "status"] = "Open - with L1"
            if pd.notna(row.eng_entered_at):
                op[i, "eng_left_at"] = at
                op[i, "eng_done_h"] = row.eng_done_h + (at - row.eng_entered_at).total_seconds() / 3600
        elif e["type"] == "ticket.call_required":
            op[i, "call_required_ev"] = True
        elif e["type"] == "ticket.eng_head":
            op[i, "eng_head_at"], op[i, "eng_head_note"] = at, e["data"]["note"]
        elif e["type"] == "ticket.call_held":
            op[i, "call_held_at"], op[i, "call_held_with"] = at, e["data"]["who"]
        elif e["type"] == "ticket.known_issue":
            op[i, "known_issue"] = e["data"]["issue"]
        elif e["type"] == "ticket.lag_mark":
            op[i, "lag_marked"] = True
        elif e["type"] == "ticket.assign":
            op[i, "assigned_agent"] = e["data"]["agent"]
    return d


def escalation_log(events: list, df: pd.DataFrame) -> pd.DataFrame:
    """One row per saved escalation: who escalated, whether the checks and a detailed note were done."""
    agent = dict(zip(df.ticket_id, df.assigned_agent))
    rows = []
    for e in events:
        if e["type"] == "ticket.assign" and e["data"]["id"] in agent:
            agent[e["data"]["id"]] = e["data"]["agent"]
        if e["type"] == "ticket.escalate" and e["data"]["id"] in agent:
            dd = e["data"]
            rows.append({"when": pd.Timestamp(e["at"]), "ticket_id": dd["id"], "agent": agent[dd["id"]],
                         "checks_done": dd["checks_done"], "checks_total": dd["checks_total"], "note": dd["note"].strip()})
    return pd.DataFrame(rows, columns=["when", "ticket_id", "agent", "checks_done", "checks_total", "note"])
