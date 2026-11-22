"""RideOps Support Control Room: application shell. Run: streamlit run app.py"""

import datetime
import os
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

import auth
import connect
import engine as E
import guide
import state
import store
import theme_patch
import ui
from views import users as users_view
from views import desk, engineering, escalations, health, insights, overview, support

st.set_page_config(page_icon=":material/support_agent:", layout="wide",
                   initial_sidebar_state="auto")
ui.inject_css()
state.show_flash()


@st.cache_resource
def _theme_patch() -> str:
    # once per server process; takes effect for page loads after this one (index.html is read per request)
    return theme_patch.apply()


THEME_PATCH = _theme_patch()

ROLES = {
    "Admin": ["scorecard", "queue", "desk", "health", "coaching", "escalations", "returns", "registry",
              "roots", "before_after", "backtests", "method", "users"],
    "All views": ["scorecard", "queue", "desk", "health", "coaching", "escalations", "returns", "registry",
                  "roots", "before_after", "backtests", "method"],
    "Head of Operations": ["scorecard", "before_after", "roots", "backtests", "method"],
    "Support lead": ["queue", "desk", "health", "coaching", "escalations", "returns", "backtests", "method"],
    "Engineering lead": ["escalations", "returns", "registry", "roots", "backtests", "method"],
    "L1 agent": ["desk", "queue", "registry", "method"],
}
# Settings live in plain session keys, not only in widget keys: st.switch_page resets widget state, which
# would silently drop the chosen role, go-live date and uploaded export.
ss = st.session_state
if "prefs_loaded" not in ss:                       # first run of this session: pick up what was chosen last time
    ss.prefs_loaded = True
    saved = store.load_prefs()
    if saved.get("role_value") in ROLES:
        ss.role_value = saved["role_value"]
    for k, v in saved.get("settings", {}).items():
        if k in E.Settings.__dataclass_fields__ and k != "eng_sla_hours":
            ss[f"set_{k}"] = v
    try:
        ss.go_live_value = datetime.date.fromisoformat(saved["go_live"]) if saved.get("go_live") else None
    except ValueError:
        ss.go_live_value = None
    if ss.go_live_value is None:
        ss.pop("go_live_value")
    ss.plain_tables = bool(saved.get("plain_tables"))
    if saved.get("welcome_seen"):
        ss.welcome_seen = True              # the welcome popup is shown once; "How to use" reopens it
    ss.prefs_saved = saved
ss.setdefault("role_value", "All views")
AUTH = auth.required()
CAN_ADMIN = True
if AUTH:                                           # sign-in is on: nothing else is built until someone signs in
    if not ss.get("user"):
        users_view.login_screen()
        st.stop()
    ss.role_value = ss.user["role"]                # the role comes from the account, not from a picker
    CAN_ADMIN = ss.user["role"] == "Admin"          # data and policy are shared by everyone: only administrators change them
allowed = ROLES[ss.role_value]
ss.allowed_pages = allowed
ctx = state.context()
open_n = len(ctx.att)
need = int((ctx.att.attention_score >= 3).sum())  # shown in the welcome dialog
esc_n = int(ctx.att.status.eq("Open - with Engineering").sum())


def page(key, fn, title, icon, url, hide=False):
    # every page stays routable (there are no logins, so the role only shapes the menu)
    return st.Page(fn, title=title, icon=icon, url_path=url, visibility="visible" if key in allowed and not hide else "hidden")


PAGES = {
    "scorecard": page("scorecard", overview.scorecard, "Scorecard", ":material/monitoring:", "scorecard"),
    "queue": page("queue", support.attention_queue, f"Attention queue · {open_n}" if open_n else "Attention queue",
                  ":material/notification_important:", "attention-queue"),
    "desk": page("desk", desk.desk, "My desk", ":material/inbox:", "my-desk"),
    "health": page("health", health.account_health, "Account health", ":material/health_and_safety:", "account-health"),
    "coaching": page("coaching", support.agent_coaching, "Agent coaching", ":material/groups:", "agent-coaching"),
    "escalations": page("escalations", escalations.escalations,
                        f"Escalations · {esc_n}" if esc_n else "Escalations", ":material/send:", "escalations"),
    "returns": page("returns", engineering.returns, "Returns from engineering", ":material/undo:", "returns"),
    "registry": page("registry", engineering.registry, "Known-issue registry", ":material/bug_report:", "known-issues"),
    "roots": page("roots", engineering.root_causes, "Root causes / feature gaps", ":material/troubleshoot:", "root-causes"),
    "users": page("users", users_view.users, "Users", ":material/manage_accounts:", "users"),
    "before_after": page("before_after", insights.before_after, "Before / after", ":material/compare_arrows:",
                         "before-after"),
    "backtests": page("backtests", insights.backtests, "Back-tests", ":material/science:", "back-tests"),
    "method": page("method", insights.methodology, "Methodology", ":material/menu_book:", "methodology"),
}
SECTIONS = {
    "Overview": ["scorecard"],
    "Support": ["queue", "desk", "health", "coaching"],
    "Engineering": ["escalations", "returns", "registry", "roots"],
    "Insights": ["before_after", "backtests", "method"],
    "Admin": ["users"],
}
ss.pages = PAGES

# ---------------- sidebar ----------------
# Streamlit's own sidebar menu: grouped, keyboard accessible, and it closes the drawer after a tap on phones.
SEARCH_SHOWN = 8       # results listed in the sidebar; the rest are one click away
ASSETS = Path(__file__).parent / "assets"
st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "mark.svg"))
nav = st.navigation({s: [PAGES[k] for k in keys] for s, keys in SECTIONS.items()}, expanded=True)
# if the role changes while viewing a page it does not use, move to that role's first page
if nav.url_path not in {PAGES[k].url_path for k in allowed}:
    st.switch_page(PAGES[allowed[0]])

sb = st.sidebar
# role_value is the single source of truth; the role can also change in the welcome dialog, so sync the
# picker to it every run (a stale picker would otherwise push its old value back after a page switch)
if AUTH:
    sb.markdown(f"Signed in as **{ss.user['name']}** · {ss.user['role']}")
    sb.button("Sign out", icon=":material/logout:", width="stretch", on_click=users_view.sign_out)
else:
    ss.role = ss.role_value
    sb.selectbox("Viewing as", [r for r in ROLES if r != "Admin"], key="role",
                 on_change=lambda: ss.update(role_value=ss.role),
                 help="Shows the views this role uses. Pick All views for the full suite. There are no accounts: this is not a lock.")
guide_row = sb.container(horizontal=True, gap="small")
if guide_row.button("How to use", icon=":material/help:", width="stretch", key="open_welcome"):
    ss.welcome_open = True
    guide.end_tour()
if guide_row.button("Tour", icon=":material/tour:", width="stretch", key="open_tour"):
    guide.start_tour()
sb.toggle("Plain tables", key="plain_tables", help="Shows tables as ordinary text tables that a screen reader can read, "
          "instead of scrolling grids. Tables where you select a row still offer a picker.")
opened_dialog = False

sb.html('<p class="rx-side-label">Find a ticket</p>')
q = sb.text_input("Find a ticket", placeholder="SUP-10042, client or keyword", label_visibility="collapsed",
                  icon=":material/search:", key="global_search")
if q.strip():
    s = q.strip().lower()
    d = ctx.d
    hits = d[d.ticket_id.str.lower().str.contains(s, regex=False) | d.client_name.str.lower().str.contains(s, regex=False)
             | d.description.str.lower().str.contains(s, regex=False)].sort_values("created_at", ascending=False)
    if hits.empty:
        sb.caption("No tickets match.")
    for _, h in hits.head(SEARCH_SHOWN).iterrows():
        state_txt = "closed" if not h.is_open else "with engineering" if h.status.endswith("Engineering") else "with L1"
        if sb.button(f"{h.ticket_id} · {h.client_name} · {h.priority} · {state_txt}", key=f"hit_{h.ticket_id}", width="stretch",
                     help=h.description, icon=":material/confirmation_number:"):
            state.ticket_dialog(h.ticket_id)
            opened_dialog = True
    if len(hits) > SEARCH_SHOWN and sb.button(f"See all {len(hits):,} results", key="search_all", width="stretch",
                                              icon=":material/list:"):
        state.show_ticket_list(f"Tickets matching “{q.strip()}”", hits.ticket_id.tolist(), "gsearch")
        opened_dialog = True
    sb.caption("Search runs when you press Enter.")

if CAN_ADMIN:
    with sb.expander("Data", icon=":material/database:"):
        ss.setdefault("upload_n", 0)  # bumping the key is the supported way to clear a file_uploader

        def use_dataset(content: bytes, name: str, source: str) -> None:
            """Check the data reads, then save it for everyone on this server and make it the active one."""
            state.prepare(content, state.settings())
            store.save_dataset(name, content, source)
            for k in ("go_live_value", "registry_for"):     # these belong to the previous data
                ss.pop(k, None)
            ss.upload_n += 1
            state.flash(f"Saved and loaded {name}", ":material/check_circle:")
            st.rerun()

        up = st.file_uploader("Ticket export (CSV)", type="csv", key=f"upload_{ss.upload_n}",
                              help="Same columns as the sample export. Saved on the server, so it is still here after a restart.")
        if up is not None:
            try:
                use_dataset(up.getvalue(), up.name, "upload")
            except state.READ_ERRORS as err:
                st.error(f"Could not read this file: {err}. Still showing the previous data.", icon=":material/error:")
        saved = store.list_datasets()
        if saved:
            labels = {d["id"]: f"{d['name']} · {d['source']} · {d['uploaded_at'].replace('T', ' ')}" for d in saved}
            ids = [None] + list(labels)
            cur = store.active_dataset()
            pick = st.selectbox("Data in use", ids, index=ids.index(cur["id"]) if cur else 0, key=f"ds_pick_{ss.upload_n}",
                                format_func=lambda i: "Sample export" if i is None else labels[i],
                                help="Every saved export stays here. Escalations and the registry are kept per export.")
            if pick != (cur["id"] if cur else None):
                store.set_active(pick)
                for k in ("go_live_value", "registry_for"):
                    ss.pop(k, None)
                st.rerun()

        st.markdown("**Connect an API**")
        api = store.kv_get("api", {}) or {}
        api_url = st.text_input("Tickets URL", value=api.get("url", ""), key="api_url", placeholder="https://example.com/api/tickets",
                                help="Returns CSV or a JSON list of tickets with the same fields as the export.")
        api_hdr = st.text_input("Token header", value=api.get("header", "Authorization"), key="api_hdr")
        api_tok = st.text_input("Token", type="password", key="api_tok", help="Sent in the header above. Never saved. "
                                "Leave empty to use the RIDEOPS_API_TOKEN setting of the server.")
        def _pull(df, mapping):
            """Use the fetched table if it has every field once mapped; otherwise ask the person to map the rest."""
            df2 = connect.apply_mapping(df, mapping)
            if connect.missing(df2, E.REQUIRED):
                ss.api_pending = connect.to_bytes(df)
                st.rerun()
            use_dataset(connect.to_bytes(df2), f"{urlparse(api_url).hostname} {datetime.datetime.now():%d %b %H:%M}", "api")

        if st.button("Fetch and save", icon=":material/cloud_download:", width="stretch", disabled=not api_url.strip()):
            try:
                frame = connect.fetch_frame(api_url, api_hdr, api_tok or os.environ.get("RIDEOPS_API_TOKEN", ""))
                store.kv_set("api", {**api, "url": api_url.strip(), "header": api_hdr.strip()})
                _pull(frame, api.get("mapping", {}))
            except (OSError, ValueError, *state.READ_ERRORS) as err:
                st.error(f"Could not fetch tickets: {err}. Still showing the previous data.", icon=":material/error:")
        if ss.get("api_pending"):
            import io

            import pandas as pd
            pending = pd.read_csv(io.BytesIO(ss.api_pending), dtype=str, keep_default_na=False)
            gaps = connect.missing(connect.apply_mapping(pending, api.get("mapping", {})), E.REQUIRED)
            st.warning(f"The API's fields do not match: {len(gaps)} missing. Say which of its fields holds each one.",
                       icon=":material/swap_horiz:")
            guess = connect.suggest(list(pending.columns), gaps)
            chosen = {}
            for gap in gaps:
                opts = [""] + list(pending.columns)
                chosen[gap] = st.selectbox(gap, opts, index=opts.index(guess[gap]) if guess.get(gap) in opts else 0,
                                           key=f"map_{gap}", format_func=lambda x: x or "Choose a field…")
            left, right = st.columns(2)
            if left.button("Save mapping and load", type="primary", width="stretch", disabled=not all(chosen.values())):
                mapping = {**api.get("mapping", {}), **chosen}
                store.kv_set("api", {**api, "mapping": mapping})
                api["mapping"] = mapping
                ss.pop("api_pending", None)
                try:
                    _pull(pending, mapping)
                except (OSError, ValueError, *state.READ_ERRORS) as err:
                    st.error(f"Could not read the mapped data: {err}", icon=":material/error:")
            if right.button("Cancel", width="stretch"):
                ss.pop("api_pending", None)
                st.rerun()
        last = store.kv_get("api_last", None)
        if last:
            st.caption(f"Last scheduled refresh: {last['at'].replace('T', ' ')} · {last['message']}")

base_cfg = E.Settings()
cur = state.settings()
changed = [f for f in E.Settings.__dataclass_fields__ if f != "eng_sla_hours" and getattr(cur, f) != getattr(base_cfg, f)]
if CAN_ADMIN:
    with sb.expander("Policy settings" + (f" · {len(changed)} changed" if changed else ""), icon=":material/tune:"):
        st.caption("Your choices, not measured. They change the numbers on every page. Changed ones are marked.")
        def _setting(field, label, **kw):
            pct_kind = isinstance(getattr(base_cfg, field), float)
            scale = 100 if pct_kind else 1
            val = getattr(cur, field) * scale
            if round(val) != round(getattr(base_cfg, field) * scale):
                label += " · changed"
            out = st.number_input(label, key=f"w_set_{field}", value=int(round(val)), **kw,
                                  on_change=lambda f=field, k=f"w_set_{field}", sc=scale: ss.update({f"set_{f}": ss[k] / sc if sc != 1 else ss[k]}))
            return out

        _setting("l1_hours", "Deadline, not escalated (hours)", min_value=1, max_value=720, step=1,
                 help="A ticket that is not escalated is on time if closed within this.")
        _setting("eng_hours", "Deadline, escalated (hours)", min_value=1, max_value=2000, step=1,
                 help="An escalated ticket is on time if closed within this.")
        _setting("window_weeks", "Recent weeks counted as 'now'", min_value=1, max_value=26, step=1)
        _setting("registry_days", "Known-issue lookback (days)", min_value=1, max_value=365, step=1,
                 help="Duplicates this recent seed the known-issue registry.")
        _setting("at_risk_days", "At-risk window (days)", min_value=1, max_value=365, step=1,
                 help="Bad experiences in this many days before the export ends count toward an at-risk account.")
        _setting("at_risk_min_bad", "Bad experiences that make an account at risk", min_value=1, max_value=50, step=1)
        _setting("slow_close_hours", "A ticket this slow is a bad experience (hours)", min_value=1, max_value=2000, step=1)
        _setting("overload_percent", "Overloaded above this % of the team average", min_value=100, max_value=500, step=10,
                 help="Open tickets per agent against the team average.")
        _setting("reopen_flag_share", "Share flagged as reopen risk (%)", min_value=1, max_value=60, step=1)
        _setting("high_impact_share", "High impact = top share by people affected (%)", min_value=1, max_value=60, step=1)
        if st.button("Reset policy settings", width="stretch", disabled=not changed):
            for f in E.Settings.__dataclass_fields__:
                ss.pop(f"set_{f}", None)
                ss.pop(f"w_set_{f}", None)
            st.rerun()
        if THEME_PATCH.startswith("failed"):
            st.caption(f"Light/dark toggle unavailable: {THEME_PATCH[8:]}. Run `python theme_patch.py` with write access "
                       "to Streamlit's folder.")
        else:
            st.caption("Light/dark: use the sun/moon button at the top right.")

source = state.data_name()
sb.html(f'<p class="rx-side-meta" style="margin:8px">Data as of <strong>{ctx.as_of:%d %b %Y}</strong> · '
        f'{len(ctx.d):,} tickets · {int(ctx.d.is_open.sum())} open<br>{source}</p>')

# how-to guide: welcome dialog on first visit in a session, or the tour (only one dialog may open per run)
if not opened_dialog:
    current = next(k for k, p in PAGES.items() if p.url_path == nav.url_path)
    guide.show(list(ROLES), allowed, current, need)

# remember role, policy settings and go-live date for next time (only written when something changed)
prefs = {"role_value": ss.role_value,
         "settings": {f: ss[f"set_{f}"] for f in E.Settings.__dataclass_fields__ if f != "eng_sla_hours" and f"set_{f}" in ss},
         "go_live": ss.go_live_value.isoformat() if ss.get("go_live_value") else None,
         "welcome_seen": bool(ss.get("welcome_seen")), "plain_tables": bool(ss.get("plain_tables"))}
if prefs != ss.get("prefs_saved"):
    store.save_prefs(prefs)
    ss.prefs_saved = prefs

nav.run()
