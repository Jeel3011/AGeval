"""
examples/agents/fleet/budget_openai.py

A hard USD spend cap for the OpenAI-powered fleet — the OpenAI analogue of
`examples/agents/budget_guard.py` (which guards Anthropic).

The fleet makes REAL OpenAI calls across ~150 agents. This guard wraps an
`OpenAI` client, projects the *worst-case* cost of each `chat.completions`
call BEFORE making it (prompt chars/4 as an input estimate + full `max_tokens`
as output, priced at the model's rate), and raises `BudgetExceeded` if the call
would push cumulative spend over the cap. After each call it reconciles using
the real `usage` returned by the API.

It is a thin proxy: `guarded.chat.completions.create(...)` behaves exactly like
the real client, so you can pass it straight into `trace_openai(client=...)`.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    """Raised when a call would push cumulative spend over the cap."""


# USD per 1,000,000 tokens (input, output). Conservative / rounded up.
_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
}
_DEFAULT_PRICE = (2.50, 10.00)  # unknown model -> assume an expensive tier


def _price_for(model: str) -> tuple[float, float]:
    for key, price in _PRICES.items():
        if model.startswith(key):
            return price
    return _DEFAULT_PRICE


def _cost(model: str, in_tokens: int, out_tokens: int) -> float:
    p_in, p_out = _price_for(model)
    return (in_tokens / 1_000_000) * p_in + (out_tokens / 1_000_000) * p_out


class _GuardedCompletions:
    def __init__(self, guard: "OpenAIBudgetGuard"):
        self._guard = guard
        self._real = guard._client.chat.completions

    def create(self, **kwargs):
        model = kwargs.get("model", "")
        max_tokens = int(kwargs.get("max_tokens", kwargs.get("max_completion_tokens", 1024)))
        in_tokens = self._estimate_input_tokens(kwargs)
        projected = _cost(model, in_tokens, max_tokens)

        if self._guard.spent + projected > self._guard.usd_cap:
            raise BudgetExceeded(
                f"Refusing OpenAI call: spent ${self._guard.spent:.4f} + projected "
                f"${projected:.4f} would exceed cap ${self._guard.usd_cap:.2f}. "
                f"({self._guard.calls} calls so far.)")

        resp = self._real.create(**kwargs)

        usage = getattr(resp, "usage", None)
        actual_in = getattr(usage, "prompt_tokens", in_tokens) if usage else in_tokens
        actual_out = getattr(usage, "completion_tokens", max_tokens) if usage else max_tokens
        self._guard._record(_cost(model, actual_in or 0, actual_out or 0))
        return resp

    def _estimate_input_tokens(self, kwargs: dict) -> int:
        blob = repr(kwargs.get("messages", "")) + repr(kwargs.get("tools", ""))
        return int(len(blob) / 4 * 1.2) + 1


class _GuardedChat:
    def __init__(self, guard: "OpenAIBudgetGuard"):
        self.completions = _GuardedCompletions(guard)


class OpenAIBudgetGuard:
    """A spend-capped proxy around an OpenAI client. Pass it wherever an OpenAI
    client is expected (e.g. trace_openai)."""

    def __init__(self, client, usd_cap: float = 3.00):
        self._client = client
        self.usd_cap = float(usd_cap)
        self.spent = 0.0
        self.calls = 0
        self.chat = _GuardedChat(self)

    def _record(self, cost: float) -> None:
        self.spent += cost
        self.calls += 1
        log.info(f"[budget] call {self.calls}: +${cost:.4f} (total ${self.spent:.4f}/${self.usd_cap:.2f})")

    def remaining(self) -> float:
        return max(0.0, self.usd_cap - self.spent)

    def report(self) -> str:
        return (f"OpenAI spend: ${self.spent:.4f} of ${self.usd_cap:.2f} cap "
                f"across {self.calls} call(s); ${self.remaining():.4f} remaining.")

    def __getattr__(self, name):
        return getattr(self._client, name)
