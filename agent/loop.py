"""The tool-calling agent.

Two properties separate this from a demo loop: every tool call is authorized
against the requesting user, and the loop returns a partial result rather than
overrunning its deadline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ops.budget import LatencyGate, Tier, LADDER
from retrieval.permissioned import Principal, PermissionedRetriever


@dataclass
class ToolCall:
    name: str
    arguments: dict
    # Recorded for the trace. An action taken without an audit entry is an
    # action nobody can review after the fact.
    authorized: bool = False
    result: str | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class AgentResult:
    answer: str
    citations: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    steps_used: int = 0
    tier: Tier = Tier.FULL
    # True when the loop stopped on the deadline rather than on completion.
    partial: bool = False


class ToolRegistry:
    """Tools, each with the permission it requires.

    A tool the user cannot invoke is not merely hidden from the model — the
    call is rejected at execution. Hiding it from the tool list is a UX
    nicety; rejecting the call is the security control, and the two must not
    be confused.
    """

    def __init__(self) -> None:
        self._tools: dict[str, tuple[callable, str]] = {}

    def register(self, name: str, fn, required_permission: str) -> None:
        self._tools[name] = (fn, required_permission)

    def available_to(self, principal: Principal) -> list[str]:
        return [
            name for name, (_fn, perm) in self._tools.items()
            if perm in principal.roles
        ]

    def invoke(self, name: str, arguments: dict,
               principal: Principal) -> ToolCall:
        call = ToolCall(name=name, arguments=arguments)
        entry = self._tools.get(name)
        if entry is None:
            call.error = f"unknown tool {name!r}"
            return call

        fn, required = entry
        # The authorization check happens HERE, at execution, using the
        # principal — never using a service identity, and never trusting that
        # the model only called tools it was offered.
        if required not in principal.roles:
            call.error = f"not authorized for {name!r}"
            return call

        call.authorized = True
        started = time.perf_counter()
        try:
            call.result = fn(principal=principal, **arguments)
        except Exception as exc:
            call.error = f"{type(exc).__name__}: {exc}"
        call.duration_ms = (time.perf_counter() - started) * 1000
        return call


class TriageAgent:
    def __init__(self, retriever: PermissionedRetriever,
                 tools: ToolRegistry, complete_fn) -> None:
        self._retriever = retriever
        self._tools = tools
        self._complete = complete_fn

    def run(self, ticket: str, principal: Principal, tier: Tier,
            latency_gate: LatencyGate) -> AgentResult:
        config = LADDER[tier]
        started = time.perf_counter()
        result = AgentResult(answer="", tier=tier)

        hits = self._retriever.search(ticket, principal, k=config.retrieval_k)
        context = "\n\n".join(
            f"[{doc.doc_id}] {doc.text}" for doc, _score in hits)

        messages = [
            {"role": "system", "content": self._system_prompt(principal)},
            {"role": "user", "content": f"Ticket:\n{ticket}\n\nPolicies:\n{context}"},
        ]

        for _ in range(config.agent_steps):
            # Check the deadline BEFORE the step, using a conservative estimate
            # of a model call. Starting a step that cannot finish wastes the
            # remaining budget and still returns nothing.
            if not latency_gate.may_continue(started, next_step_est_s=1.5):
                result.partial = True
                break

            result.steps_used += 1
            response = self._complete(
                messages,
                model=config.model,
                tools=self._tools.available_to(principal),
            )

            if call_request := response.get("tool_call"):
                call = self._tools.invoke(
                    call_request["name"], call_request["arguments"], principal)
                result.tool_calls.append(call)
                messages.append({
                    "role": "tool",
                    "content": call.result if call.error is None
                    else f"error: {call.error}",
                })
                continue

            result.answer = response["content"]
            result.citations = [doc.doc_id for doc, _ in hits]
            return result

        # Loop exhausted or deadline hit. Return what we have, marked partial,
        # rather than an error — a partially reasoned triage that a human
        # finishes beats nothing at all.
        if not result.answer:
            result.answer = (
                "Unable to complete triage within budget. "
                "Routing to human review.")
            result.partial = True
        return result

    def _system_prompt(self, principal: Principal) -> str:
        return (
            "Triage the support ticket. Assign one category and one priority.\n"
            "Cite the policy justifying the priority as [policy-id §section].\n"
            "Use ONLY the policies provided. If none justifies a priority, "
            "assign normal and say which policy you checked.\n"
            f"Acting for user {principal.user_id}."
        )
