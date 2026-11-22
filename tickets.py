"""Ticket-level helpers for the detail view and My desk. Ported from the reference app's ticket drawer
(history of the same issue, next move, who has the ball), using this app's flags and settings."""
import numpy as np
import pandas as pd

import engine as E


def owner(t) -> str:
    return "Engineering" if t.status == "Open - with Engineering" else f"L1 ({t.assigned_agent})" if t.is_open else "Closed"


def history(d: pd.DataFrame, t) -> dict:
    """The same issue (same wording with numbers masked) seen before this ticket, using only earlier tickets."""
    peers = d[(d.template == t.template) & (d.ticket_id != t.ticket_id) & (d.created_at < t.created_at)]
    esc = peers[peers.esc]
    decided = esc[esc.eng_outcome.notna()]
    return {
        "peers": len(peers), "esc_rate": len(esc) / len(peers) if len(peers) else np.nan,
        "outcomes": decided.eng_outcome.value_counts().to_dict(), "decided": len(decided),
        "med_l1": peers[~peers.esc].ttr_h.median(), "med_esc": esc.ttr_h.median(),
        "recent": esc[(t.created_at - esc.created_at).between(pd.Timedelta(0), pd.Timedelta(days=E.LONG_OPEN_DAYS))]
        .sort_values("created_at", ascending=False).head(5),
    }


def next_moves(t, flags: list, cfg: E.Settings) -> list:
    """What the person holding the ticket should do next, one line per flag that applies."""
    say = {
        "Overdue, engineering lane": f"Past the {cfg.eng_hours}h escalated deadline. Ask engineering for an ETA on {t.eng_ticket_id} "
                                     "and send the client a dated update.",
        "Overdue, L1 lane": f"Past the {cfg.l1_hours}h deadline for tickets that are not escalated. Reply or resolve today.",
        "Returned by eng, waiting on L1": "Engineering sent it back. L1 owns it now: apply their answer and close, or "
                                          "re-escalate only with the missing details.",
        "Bounced 2+ times": "It has gone to engineering more than once. Agree the cause on a call before sending it again.",
        "Reopened by client": "The fix did not hold. Call the client and confirm what is still broken before closing.",
        "No first response": "Reply to the client now.",
        "High impact, low priority": "Many people are affected. Treat it as P1 or P2 whatever its label says.",
        "Reopen risk: confirm before closing": "Tickets like this reopen more than most. Confirm the fix with the client before closing.",
        "At-risk accounts": f"This client had {cfg.at_risk_min_bad} or more bad experiences in the last {cfg.at_risk_days} days. "
                            "Tell the account manager and send a dated update.",
        "Tickets open 7+ days": "Open for over a week. Decide today: resolve, escalate with a date, or tell the client why not.",
        "Call required: engineering + agent": "Second escalation: it cannot go back to support. The engineer and the agent "
                                              "talk to each other and agree the cause.",
    }
    if pd.notna(getattr(t, "call_held_at", pd.NaT)):
        say["Call required: engineering + agent"] = (f"The call was held on {t.call_held_at:%d %b} with {t.call_held_with}. "
                                                     "Engineering can now mark the ticket fixed.")
    out = [say[f] for f in flags if f in say]
    if t.status == "Open - with Engineering" and pd.notna(t.eng_outcome):
        out.append(f'Engineering recorded "{t.eng_outcome}" but still holds the ticket. Ask them to close it out.')
    return out or (["No action needed beyond normal follow-up."] if t.is_open else [])


def packet_from_event(e: dict, t) -> str:
    """The text L1 sent with an escalation: each check, whether it was done, the answer given, and the note."""
    d = e["data"]
    lines = [f"Ticket: {t.ticket_id} · {t.client_name} · {t.priority}", f"Category: {t.category}", f"Issue: {t.description}", ""]
    if d.get("answers"):
        lines.append("Checks:")
        for a in d["answers"]:
            lines.append(f"  [{'x' if a['done'] else ' '}] {a['check']}")
            if a.get("answer"):
                lines.append(f"      Answer: {a['answer']}")
        lines.append("")
    else:
        lines.append(f"Checks done: {d['checks_done']} of {d['checks_total']}")
    return "\n".join(lines + [f"Findings: {d['note'].strip() or '(none)'}"])


def _answered(d: dict) -> str:
    got = [f"{a['check']}: {a['answer']}" for a in d.get("answers", []) if a.get("answer")]
    return f" Answers: {'; '.join(got)}." if got else ""


SAY = {"ticket.escalate": lambda d: "Escalated to engineering" + (f". Note: {d['note']}" if d["note"].strip() else ". No note.")
       + _answered(d),
       "ticket.return": lambda d: f"Engineering returned it: {d['reason']}",
       "ticket.fixed": lambda d: "Engineering marked it fixed",
       "ticket.call_required": lambda d: "Call required: engineering + agent",
       "ticket.eng_head": lambda d: f"Escalated to the engineering head. {d['note']}".strip(),
       "ticket.lag_mark": lambda d: "Marked as engineering lag",
       "ticket.call_held": lambda d: f"Call held with {d['who']}" + (f". {d['note']}" if d.get("note") else ""),
       "ticket.known_issue": lambda d: f"Linked to a known issue: {d['issue']}. Not escalated",
       "ticket.assign": lambda d: f"Assigned to {d['agent']}"}


def describe(e: dict) -> str:
    return SAY[e["type"]](e["data"])


def timeline(events: list, ticket_id: str) -> list:
    """Saved actions for one ticket, oldest first, as (time, who, text)."""
    return [(e["at"].replace("T", " "), e["by"], describe(e)) for e in events
            if e["type"] in SAY and e["data"].get("id") == ticket_id]


PRIORITIES = ["P1", "P2", "P3", "P4"]


def suggest_priority(t, d: pd.DataFrame, cfg: E.Settings) -> tuple:
    """(priority, reasons). The agent decides; the label stays unless they change it. Each rule moves it up one level."""
    p = PRIORITIES.index(t.priority) if t.priority in PRIORITIES else len(PRIORITIES) // 2
    why = []
    if pd.notna(t.affected) and t.affected >= E.high_impact_threshold(d, cfg) and p > 1:
        p = 1
        why.append(f"{int(t.affected)} people affected")
    if t.at_risk and p > 0:
        p -= 1
        why.append("at-risk account")
    return PRIORITIES[p], why


def handover(agent: str, rows: pd.DataFrame) -> str:
    """Shift-handover note for one agent's open tickets."""
    mine = rows[rows.assigned_agent == agent]
    eng, act = mine[mine.status == "Open - with Engineering"], mine[mine.status != "Open - with Engineering"]
    ln = lambda r: f"- {r.ticket_id} {r.client_name} ({r.priority}): {r.description}"  # noqa: E731
    out = [f"Handover from {agent}: {len(mine)} open tickets", "", f"With L1 ({len(act)}):"]
    out += [ln(r) + (f" | {r.flags}" if r.flags else "") for r in act.itertuples()]
    out += ["", f"Waiting on Engineering ({len(eng)}):"] + [ln(r) + f" | {r.eng_ticket_id}" for r in eng.itertuples()]
    return "\n".join(out)
