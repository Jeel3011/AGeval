"""
19 — LangGraph Supervisor Multi-Agent Team (real LangGraph StateGraph)

The canonical hierarchical multi-agent pattern: a *supervisor* node decides
which specialist worker should act next (a billing agent, a support agent, or a
logistics agent), each worker is its own tool-using ReAct sub-agent, and control
returns to the supervisor until the task is done. This is how teams build
"agent teams" in LangGraph.

Every worker's tool call flows into ONE AGeval AgentSession, so the whole
multi-agent collaboration is captured as a single scored episode — proving
AGeval handles multi-agent routing, not just single loops.

Run:  python examples/agents/19_langgraph_supervisor_team.py
Needs: OPENAI_API_KEY, and `pip install langgraph langchain-openai`.
"""

from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from typing import Literal

from pydantic import BaseModel

from examples.agents._common import OPENAI_MODEL, have_openai, require, run_and_report
from examples.agents.toolkit import (
    check_inventory,
    create_ticket,
    get_customer,
    process_payment,
    search_flights,
    vector_search,
)

WORKERS = ["billing", "support", "logistics"]


class _Route(BaseModel):
    """Supervisor routing decision. Module-level so its Literal annotation
    resolves cleanly when pydantic builds the JSON schema."""

    next: Literal["billing", "support", "logistics", "FINISH"]


# Under `from __future__ import annotations` the field annotation is a deferred
# string; force pydantic to resolve it now (Literal is in scope here).
_Route.model_rebuild()


def build_and_run() -> dict:
    if not require(have_openai(), "OpenAI"):
        return {}
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_core.tools import tool as lc_tool
        from langchain_openai import ChatOpenAI
        from langgraph.graph import END, START, StateGraph
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import create_react_agent

        from examples.agents._lgstate import last_text
    except ImportError:
        print("  [skip] LangGraph not installed. Run: pip install langgraph langchain-openai")
        return {}

    from typing import Annotated, TypedDict

    from ageval import AgentSession

    # Functional TypedDict → real annotation objects (not deferred strings), so
    # LangGraph's get_type_hints resolves it even under future-annotations.
    _TeamState = TypedDict("_TeamState",
                           {"messages": Annotated[list, add_messages], "next": str})

    session = AgentSession(agent_id="langgraph_supervisor_team_v1",
                           task="resolve a cross-functional request via a supervised agent team")
    session.start()

    # ---- Specialist tools, each AGeval-traced ----
    @lc_tool
    def lookup_customer(customer_id: str) -> str:
        """Look up a customer by id."""
        return str(session.traced(get_customer, reasoning="billing: identify account")(customer_id))

    @lc_tool
    def charge(amount: float) -> str:
        """Charge the customer's card."""
        return str(session.traced(process_payment, reasoning="billing: take payment")(amount, "USD", "card"))

    @lc_tool
    def kb(query: str) -> str:
        """Search the knowledge base."""
        return str(session.traced(vector_search, reasoning="support: find policy")(query))

    @lc_tool
    def ticket(subject: str, priority: str = "P3") -> str:
        """Open a support ticket."""
        return str(session.traced(create_ticket, reasoning="support: escalate")(subject, priority))

    @lc_tool
    def stock(sku: str) -> str:
        """Check inventory for a SKU."""
        return str(session.traced(check_inventory, reasoning="logistics: check stock")(sku))

    @lc_tool
    def flights(origin: str, destination: str, date: str) -> str:
        """Search shipping/flight options."""
        return str(session.traced(search_flights, reasoning="logistics: find routes")(origin, destination, date))

    billing_agent = create_react_agent(ChatOpenAI(model=OPENAI_MODEL, temperature=0),
                                       [lookup_customer, charge])
    support_agent = create_react_agent(ChatOpenAI(model=OPENAI_MODEL, temperature=0), [kb, ticket])
    logistics_agent = create_react_agent(ChatOpenAI(model=OPENAI_MODEL, temperature=0), [stock, flights])
    worker_graphs = {"billing": billing_agent, "support": support_agent, "logistics": logistics_agent}

    # ---- Supervisor: a structured-output router (Route defined at module level
    # so pydantic can resolve its Literal annotation under
    # `from __future__ import annotations`) ----
    supervisor_llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0).with_structured_output(_Route)

    def supervisor(state):
        decision = supervisor_llm.invoke([
            SystemMessage(content=(
                "You are the supervisor of a team: billing, support, logistics. "
                "Given the conversation, decide which worker should act NEXT to make "
                "progress, or FINISH when the user's full request has been handled. "
                "Each worker has already-recorded results in the messages. Do not "
                "repeat a worker once its part is done.")),
            *state["messages"],
        ])
        session.record_step(tool_name="supervisor_route",
                            tool_input={"messages": len(state["messages"])},
                            tool_output={"next": decision.next}, success=True,
                            reasoning="supervisor decides the next worker")
        return {"next": decision.next}

    def make_worker(name):
        def worker(state):
            # Cap each sub-agent so a worker that loops can't dominate the episode.
            result = worker_graphs[name].invoke(
                {"messages": state["messages"]}, {"recursion_limit": 8})
            # Hand the worker's final answer back to the shared transcript.
            last = result["messages"][-1]
            text = getattr(last, "content", str(last)) or f"({name} acted)"
            return {"messages": [AIMessage(content=f"[{name}] {text}", name=name)]}
        return worker

    # Supervised graph: supervisor → worker → supervisor → … → END
    g = StateGraph(_TeamState)
    g.add_node("supervisor", supervisor)
    for w in WORKERS:
        g.add_node(w, make_worker(w))
        g.add_edge(w, "supervisor")
    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        lambda s: s["next"],
        {"billing": "billing", "support": "support", "logistics": "logistics", "FINISH": END},
    )
    graph = g.compile()

    result = graph.invoke(
        {"messages": [HumanMessage(content=(
            "Customer C-1001 wants to (a) be charged $120 for an add-on, (b) know whether "
            "their enterprise SLA covers a recent outage, and (c) confirm SKU-GRN-CAP is in "
            "stock to ship them a gift. Handle all three."))]},
        {"recursion_limit": 40},
    )

    session.finish()
    return {"episode_id": session.episode_id, "final_content": last_text(result)}


if __name__ == "__main__":
    raise SystemExit(run_and_report("LangGraph Supervisor Team", build_and_run))
