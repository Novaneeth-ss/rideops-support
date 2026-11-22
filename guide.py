"""'How to use' guide: a role-aware welcome dialog and a step-by-step tour of the role's pages.

The tour moves to each page as you step, so the page behind the dialog is the one being explained.
"""
from html import escape

import streamlit as st

import auth
import ui

# what each page is for, and one thing to try there
STEPS = {
    "scorecard": ("Is support getting better? The north star tracks tickets closed on time and not reopened.",
                  "Compare the recent weeks with the target in the Targets table."),
    "queue": ("Open tickets ranked by what needs action now. Overdue and returned tickets come first.",
              "Filter by 'Returned by eng, waiting on L1', then select a row for details."),
    "desk": ("One agent's open tickets with the next step, the context and the checks to run before escalating.",
             "Pick a ticket, read the next step, then use Escalation check to send it to engineering."),
    "health": ("Accounts with repeated bad experiences, and a support report for any client.",
               "Select an account to see its bad tickets and the monthly report."),
    "escalations": ("Tickets with engineering now. Return one to L1, mark it fixed, or see that it needs a call.",
                    "Select a ticket under Act on an escalation. A second escalation cannot be returned."),
    "coaching": ("Every agent compared with the others, with the main point to discuss and the load balance.",
                 "Switch to 1:1 prep at the top, or use the 1:1 prep button on an agent."),
    "returns": ("Why escalations come back to L1, by week and by category, and which are still waiting.",
                "Set a go-live date on the Before / after page to see returns after the workflow change."),
    "registry": ("Issues engineering has confirmed. L1 links tickets to them instead of escalating again.",
                 "Mark an issue 'Fixed - closed' when its fix ships, then Save changes."),
    "roots": ("Recurring issues ranked by the support hours they consume.",
              "Fix the top of this list first: it removes tickets instead of handling them faster."),
    "users": ("Who can sign in and what they can do.", "Add a user, give them a role, and share the starting password privately."),
    "before_after": ("The same measures before and after the workflow go-live date.",
                     "Pick the go-live date on this page, then compare."),
    "backtests": ("What was tested on tickets the rules had not seen, and what was dropped.",
                  "Read why escalations are never blocked automatically."),
    "method": ("How every number in the app is defined, and the known limits.",
               "Check the north star definition before quoting it."),
}

# the 3 tasks each role starts with: (task, page key)
TASKS = {
    "Admin": [("See if support is improving", "scorecard"), ("Find tickets that need action now", "queue"),
              ("Add or change a user", "users")],
    "All views": [("See if support is improving", "scorecard"), ("Find tickets that need action now", "queue"),
                  ("Escalate a ticket the right way", "desk")],
    "Head of Operations": [("See if support is improving", "scorecard"),
                           ("Compare before and after the workflow change", "before_after"),
                           ("See which issues cost the most time", "roots")],
    "Support lead": [("Find tickets that need action now", "queue"), ("Prepare a 1:1 with an agent", "coaching"),
                     ("Call the accounts at risk", "health")],
    "Engineering lead": [("Work the open escalations", "escalations"), ("See why escalations come back", "returns"),
                         ("Keep the known-issue list current", "registry")],
    "L1 agent": [("Work my open tickets and escalate the right way", "desk"), ("Find tickets that need action now", "queue"), ("Check for a known issue first", "registry")],
}

CSS = """
.rx-dots { display: flex; gap: 6px; margin: 0 0 var(--space-3); }
.rx-dots span { width: 8px; height: 8px; border-radius: 50%; background: var(--color-border); }
.rx-dots span.on { background: var(--color-primary); }
.rx-tip { background: var(--color-info-bg); color: var(--color-text-primary); border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4); font-size: var(--type-body-size); margin: var(--space-3) 0 var(--space-2); }
.rx-tip b { color: var(--color-info); }
/* Streamlit shrinks markdown headings inside dialogs, so size these explicitly */
.rx-dlg-h { font-size: 1.3rem; line-height: 1.3; font-weight: 600; color: var(--color-text-primary);
  margin: var(--space-2) 0 var(--space-1); }
"""


def _ss():
    return st.session_state


def start_tour(step: int = 0) -> None:
    _ss().tour_step, _ss().tour_open = step, True


def end_tour() -> None:
    _ss().tour_open = False


def _go(key: str) -> None:
    st.switch_page(_ss().pages[key])


@ui.popup("Welcome to RideOps Support", icon=":material/waving_hand:")
def welcome(roles: list, need: int) -> None:
    st.html(f"<style>{CSS}</style>")
    role = _ss().role_value  # read live: changing the role below reruns only this dialog
    st.caption("Support control room for ticket health, escalations and engineering returns.")
    _ss().welcome_role = role  # keep in sync with the sidebar picker
    if not auth.required():          # with sign-in on, the role belongs to the account and cannot be picked here
        st.selectbox("You're viewing as", [r for r in roles if r != "Admin"], key="welcome_role",
                     help="Changes which pages appear in the menu.",
                     on_change=lambda: _ss().update(role_value=_ss().welcome_role))
    st.html('<h2 class="rx-dlg-h">Start here</h2>')
    for i, (task, key) in enumerate(TASKS.get(role, TASKS["All views"]), 1):
        page = _ss().pages[key]
        note = f"{need} open tickets need attention" if key == "queue" and need else STEPS.get(key, ("", ""))[0]
        left, right = st.columns([5, 1], vertical_alignment="center")
        left.markdown(f"**{i} · {task}**  \n{page.title.split(' · ')[0]} — {note}")
        if right.button("Go", key=f"welcome_go_{i}_{key}", icon=":material/arrow_forward:", width="stretch"):
            _go(key)
    st.caption("Tip: search any ticket from the sidebar. Upload a newer export or connect an API under Data. "
               "Deadlines and other policy settings are under Policy settings. Reopen this guide any time with How to use.")
    a, b = st.columns(2)
    if a.button("Take the tour", type="primary", icon=":material/tour:", width="stretch"):
        start_tour()
        st.rerun()
    if b.button("Done", width="stretch"):
        st.rerun()


@ui.popup("Tour", icon=":material/tour:", on_dismiss=end_tour)
def tour(keys: list) -> None:
    st.html(f"<style>{CSS}</style>")
    i = min(_ss().get("tour_step", 0), len(keys) - 1)
    key = keys[i]
    page = _ss().pages[key]
    what, tip = STEPS.get(key, ("", ""))      # a page without a written step still gets a step, never an error
    dots = "".join(f'<span class="{"on" if j <= i else ""}"></span>' for j in range(len(keys)))
    st.html(f'<div class="rx-dots" role="img" aria-label="Step {i + 1} of {len(keys)}">{dots}</div>')
    st.caption(f"Step {i + 1} of {len(keys)}")
    st.html(f'<h2 class="rx-dlg-h">{escape(page.title.split(" · ")[0])}</h2>')
    st.write(what)
    if tip:
        st.html(f'<div class="rx-tip"><b>Try it:</b> {escape(tip)}</div>')
    back, skip, nxt = st.columns([1, 1, 1])
    if back.button("Back", icon=":material/arrow_back:", disabled=i == 0, width="stretch"):
        _ss().tour_step = i - 1
        _go(keys[i - 1])
    if skip.button("End tour", width="stretch"):
        end_tour()
        st.rerun()
    last = i == len(keys) - 1
    if nxt.button("Finish" if last else "Next", type="primary", width="stretch",
                  icon=":material/check:" if last else ":material/arrow_forward:"):
        if last:
            end_tour()
            st.toast("Tour finished. Reopen it any time from How to use.", icon=":material/check_circle:")
            st.rerun()
        _ss().tour_step = i + 1
        _go(keys[i + 1])


def show(roles: list, allowed: list, current_key: str, need: int) -> None:
    """Call once per run from the app shell. Opens at most one guide dialog."""
    ss = _ss()
    if ss.get("tour_open"):
        i = min(ss.get("tour_step", 0), len(allowed) - 1)
        if allowed[i] != current_key:  # keep the explained page behind the dialog
            _go(allowed[i])
        tour(allowed)
    elif not ss.get("welcome_seen") or ss.pop("welcome_open", False):
        ss.welcome_seen = True
        welcome(roles, need)
