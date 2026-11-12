"""Sequence 2: schedule the call. A LangGraph agent with five nodes.

check_calendar -> propose_time -> (pause for a reply) -> handle_reply
handle_reply branches: confirmed -> book_meeting, counter -> back to check_calendar,
out of rounds or out of time -> escalate.

The brief names four nodes but wires an edge to book_meeting, so it is a fifth.
crm_logged is in the state with nothing to set it, so book_meeting sets it.

The pause is real: the graph stops after propose_time and its state is checkpointed
in Postgres. Nothing polls. The reviewer's Check replies action is what resumes it,
which is the only scheduler a serverless deployment has.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import config, db, mailer, scheduling

PAUSE_NODE = "propose_time"
_MEMORY_SAVER = None


class State(TypedDict, total=False):
    company_id: int
    reply_status: str
    calendar_checked: bool
    times_proposed: int
    reply_round: int
    meeting_status: str
    crm_logged: bool
    slots: list
    reply_body: str
    confirmed_slot: str
    note: str


def _company(state):
    return db.get_company(state["company_id"])


def _store(state, **fields):
    db.update_company(state["company_id"], **fields)


# --- nodes ------------------------------------------------------------------

def check_calendar(state: State) -> State:
    slots = scheduling.free_slots()
    _store(state, calendar_checked="yes", proposed_slots_json=slots)
    return {"calendar_checked": True, "slots": slots,
            "note": f"{len(slots)} free slots found"}


def propose_time(state: State) -> State:
    company = _company(state)
    slots = state.get("slots") or scheduling.free_slots()
    scheduling.send_times(company, slots)
    count = (state.get("times_proposed") or 0) + 1
    # reply_status stays as Sequence 1 left it. Sequence 2 keeps its own progress in
    # meeting_status; writing no_reply here destroyed the interested verdict that
    # qualified the company, and with it the record of why scheduling ever started.
    _store(state, times_proposed=count, proposed_at=db.utcnow(),
           meeting_status="awaiting_reply")
    db.log("proposed_times", ", ".join(slots), state["company_id"])
    return {"times_proposed": count, "meeting_status": "awaiting_reply",
            "note": "times sent, waiting for a reply"}


def handle_reply(state: State) -> State:
    company = _company(state)
    body = (state.get("reply_body") or "").strip()
    slots = state.get("slots") or (db.loads_list(company["proposed_slots_json"]))

    if not body:
        return {"note": "no reply yet"}

    verdict = scheduling.read_scheduling_reply(body, slots)
    _store(state, reply_quote=verdict["quote"])
    if verdict["outcome"] == "confirmed":
        return {"confirmed_slot": verdict["slot"], "reply_status": "confirmed",
                "note": f"confirmed {verdict['slot']}"}
    if verdict["outcome"] == "counter":
        rounds = (state.get("reply_round") or 0) + 1
        _store(state, reply_round=rounds, calendar_checked="no")
        return {"reply_round": rounds, "calendar_checked": False,
                "reply_status": "counter", "note": f"counter-proposed, round {rounds}"}
    return {"reply_status": "neither", "note": "reply said nothing about times"}


def book_meeting(state: State) -> State:
    company = _company(state)
    slot = state["confirmed_slot"]
    scheduling.send_invite(company, slot)
    _store(state, meeting_time=slot, meeting_status="booked", crm_logged="yes")
    db.log("meeting_booked", slot, state["company_id"])
    return {"meeting_status": "booked", "crm_logged": True,
            "note": f"booked {slot}, invite sent to TO_EMAIL"}


def escalate(state: State) -> State:
    reason = state.get("note") or "handed off"
    _store(state, meeting_status="escalated", crm_logged="yes")
    db.log("escalated", reason, state["company_id"])
    return {"meeting_status": "escalated", "crm_logged": True,
            "note": f"handed off to the Growth Lead: {reason}"}


# --- edges ------------------------------------------------------------------

def after_reply(state: State) -> str:
    if state.get("confirmed_slot"):
        return "book_meeting"
    if (state.get("reply_round") or 0) >= config.MAX_REPLY_ROUNDS:
        return "escalate"
    if state.get("reply_status") == "counter":
        return "check_calendar"
    # Anything else - a reply that said nothing about times, or silence that has
    # run past the deadline - is a person's problem, not the agent's.
    return "escalate"


def past_deadline(company_id):
    company = db.get_company(company_id)
    when = company["proposed_at"] if company else None
    if not when:
        return False
    sent = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now - sent > timedelta(hours=config.REPLY_DEADLINE_HOURS)



def build(checkpointer):
    graph = StateGraph(State)
    graph.add_node("check_calendar", check_calendar)
    graph.add_node("propose_time", propose_time)
    graph.add_node("handle_reply", handle_reply)
    graph.add_node("book_meeting", book_meeting)
    graph.add_node("escalate", escalate)

    graph.add_edge(START, "check_calendar")
    graph.add_edge("check_calendar", "propose_time")
    graph.add_edge("propose_time", "handle_reply")
    graph.add_conditional_edges("handle_reply", after_reply,
                                ["book_meeting", "check_calendar", "escalate"])
    graph.add_edge("book_meeting", END)
    graph.add_edge("escalate", END)
    # The pause the brief asks for: stop after the times go out, resume when a
    # reply arrives. Checkpointed, so the pause survives a cold start.
    return graph.compile(checkpointer=checkpointer, interrupt_after=[PAUSE_NODE])


# --- running it -------------------------------------------------------------

@contextmanager
def runner():
    """A compiled graph with durable checkpointing when a database is configured."""
    url = config.get("DATABASE_URL")
    if url:
        from langgraph.checkpoint.postgres import PostgresSaver

        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()
            yield build(saver)
    else:
        # One saver for the whole process: a fresh MemorySaver per call would lose
        # the pause between propose_time and the reply that resumes it.
        global _MEMORY_SAVER
        if _MEMORY_SAVER is None:
            from langgraph.checkpoint.memory import MemorySaver

            _MEMORY_SAVER = MemorySaver()
        yield build(_MEMORY_SAVER)


def thread_for(company_id):
    """The checkpoint thread this company's current run lives on.

    Stored rather than derived, so a company can be scheduled more than once: a
    finished graph cannot be restarted on the same thread.
    """
    company = db.get_company(company_id)
    thread = (company["thread_id"] if company else None) or f"company-{company_id}"
    return {"configurable": {"thread_id": thread}}


def start(company_id):
    """Run from check_calendar until the pause after propose_time."""
    thread = f"company-{company_id}-{db.utcnow().replace(' ', 'T')}"
    db.update_company(company_id, thread_id=thread, reply_round=0, times_proposed=0,
                      crm_logged="no", meeting_status=None, meeting_time=None,
                      proposed_at=None)
    with runner() as graph:
        state = graph.invoke({"company_id": company_id, "reply_round": 0,
                              "times_proposed": 0}, thread_for(company_id))
    return state


def resume(company_id, reply_body=""):
    """Continue a paused graph, with whatever the prospect wrote (or nothing)."""
    config_ = thread_for(company_id)
    with runner() as graph:
        snapshot = graph.get_state(config_)
        if not snapshot.next:
            return {"note": "not waiting on anything", "finished": True}
        # Silence before the deadline is not an outcome. Leave the graph paused
        # rather than advancing it into a decision it has no grounds to make.
        if not reply_body and not past_deadline(company_id):
            return {"note": "still waiting, the reply deadline has not passed",
                    "finished": False}
        graph.update_state(config_, {"reply_body": reply_body})
        state = graph.invoke(None, config_)
        after = graph.get_state(config_)
    state = dict(state)
    state["finished"] = not after.next
    return state
