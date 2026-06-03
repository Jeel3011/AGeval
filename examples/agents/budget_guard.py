"""
examples/agents/budget_guard.py

A hard spend cap for the Anthropic example runs.

Why: the Anthropic agents make REAL Claude calls. When you (the maintainer)
plug in your own ANTHROPIC_API_KEY to test those paths, this guard guarantees
the whole session cannot exceed a dollar budget (default $0.50).

How it works:
  - `BudgetGuard` wraps an `Anthropic` client. It intercepts `messages.create`,
    estimates the *worst-case* cost of the call BEFORE making it (input tokens
    counted via the client's token counter when available, output tokens
    assumed to be the full `max_tokens`), and refuses the call if it would push
    cumulative spend over the cap.
  - After each call it reconciles spend using the real `usage` returned by the
    API, so the running total reflects actual tokens, not the estimate.
  - It is a thin proxy: `guarded.messages.create(...)` behaves exactly like the
    real client, so you can pass `guarded` straight into `trace_anthropic`.

Prices are USD per 1M tokens and are easy to update. They are intentionally
slightly conservative (rounded up) so the guard errs toward stopping early.

Usage:
    from anthropic import Anthropic
    from examples.agents.budget_guard import BudgetGuard

    client = BudgetGuard(Anthropic(), usd_cap=0.50)
    trace_anthropic(client=client, ..., model="claude-haiku-4-5-20251001")
    print(client.report())   # what was spent
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    """Raised when a call would push cumulative spend over the cap."""


# USD per 1,000,000 tokens. (input, output). Conservative / rounded up.
# Update these if Anthropic pricing changes.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (15.00, 75.00),
    "claude-opus-4-7": (15.00, 75.00),
    "claude-opus-4-6": (15.00, 75.00),
}
# Fallback if a model id isn't recognised: assume the most expensive tier so the
# guard never *under*-charges.
_DEFAULT_PRICE = (15.00, 75.00)


def _price_for(model: str) -> tuple[float, float]:
    for key, price in _PRICES.items():
        if model.startswith(key):
            return price
    return _DEFAULT_PRICE


def _cost(model: str, in_tokens: int, out_tokens: int) -> float:
    p_in, p_out = _price_for(model)
    return (in_tokens / 1_000_000) * p_in + (out_tokens / 1_000_000) * p_out


class _GuardedMessages:
    def __init__(self, guard: "BudgetGuard"):
        self._guard = guard
        self._real = guard._client.messages

    def create(self, **kwargs):
        model = kwargs.get("model", "")
        max_tokens = int(kwargs.get("max_tokens", 1024))

        # Estimate input tokens (worst-case prompt size) when we can.
        in_tokens = self._estimate_input_tokens(kwargs)
        projected = _cost(model, in_tokens, max_tokens)

        if self._guard.spent + projected > self._guard.usd_cap:
            raise BudgetExceeded(
                f"Refusing Anthropic call: spent ${self._guard.spent:.4f} + projected "
                f"${projected:.4f} would exceed cap ${self._guard.usd_cap:.2f}. "
                f"({self._guard.calls} calls so far.)"
            )

        resp = self._real.create(**kwargs)

        # Reconcile with the real usage returned by the API.
        usage = getattr(resp, "usage", None)
        actual_in = getattr(usage, "input_tokens", in_tokens) if usage else in_tokens
        actual_out = getattr(usage, "output_tokens", max_tokens) if usage else max_tokens
        self._guard._record(_cost(model, actual_in or 0, actual_out or 0))
        return resp

    def _estimate_input_tokens(self, kwargs: dict) -> int:
        """Best-effort input-token count. Uses the SDK's count_tokens when
        available; otherwise a chars/4 heuristic (then padded 20%)."""
        try:
            count = self._guard._client.messages.count_tokens(
                model=kwargs.get("model"),
                messages=kwargs.get("messages", []),
                system=kwargs.get("system"),
                tools=kwargs.get("tools"),
            )
            return int(getattr(count, "input_tokens", 0)) or 1
        except Exception:
            blob = repr(kwargs.get("messages", "")) + repr(kwargs.get("system", "")) + repr(kwargs.get("tools", ""))
            return int(len(blob) / 4 * 1.2) + 1


class BudgetGuard:
    """A spend-capped proxy around an Anthropic client.

    Pass the guard wherever a client is expected (e.g. trace_anthropic). Any
    call that would breach `usd_cap` raises BudgetExceeded *before* hitting the
    API, so you never spend past the cap.
    """

    def __init__(self, client, usd_cap: float = 0.50):
        self._client = client
        self.usd_cap = float(usd_cap)
        self.spent = 0.0
        self.calls = 0
        self.messages = _GuardedMessages(self)

    def _record(self, cost: float) -> None:
        self.spent += cost
        self.calls += 1
        log.info(f"[budget] call {self.calls}: +${cost:.4f} (total ${self.spent:.4f}/${self.usd_cap:.2f})")

    def remaining(self) -> float:
        return max(0.0, self.usd_cap - self.spent)

    def report(self) -> str:
        return (f"Anthropic spend: ${self.spent:.4f} of ${self.usd_cap:.2f} cap "
                f"across {self.calls} call(s); ${self.remaining():.4f} remaining.")

    # Transparently expose any other client attributes (models, beta, etc.).
    def __getattr__(self, name):
        return getattr(self._client, name)
