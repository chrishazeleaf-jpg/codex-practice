"""Daily spend tracking. Every model call is priced and recorded per agent."""
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("BUDGET")

# USD per million tokens: input, output, cache write, cache read
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
}
WEB_SEARCH_USD = 0.01


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def cost_of(model: str, usage) -> float:
    if usage is None:
        return 0.0
    p_in, p_out, p_write, p_read = PRICES.get(model, PRICES["claude-opus-5-5"])

    def n(field):
        return getattr(usage, field, 0) or 0

    usd = (n("input_tokens") * p_in + n("output_tokens") * p_out
           + n("cache_creation_input_tokens") * p_write
           + n("cache_read_input_tokens") * p_read) / 1e6
    server = getattr(usage, "server_tool_use", None)
    if server is not None:
        usd += (getattr(server, "web_search_requests", 0) or 0) * WEB_SEARCH_USD
    return usd


class Budget:
    """daily_usd <= 0 means no cap."""

    def __init__(self, daily_usd: float, path: Path):
        self.daily_usd = daily_usd
        self.path = Path(path)
        self._lock = threading.Lock()
        self._days = json.loads(self.path.read_text()) if self.path.exists() else {}

    def record(self, model: str, usage, agent: str) -> float:
        usd = cost_of(model, usage)
        if not usd:
            return 0.0
        with self._lock:
            day = self._days.setdefault(_today(), {"total": 0.0, "by_agent": {}})
            day["total"] += usd
            day["by_agent"][agent] = day["by_agent"].get(agent, 0.0) + usd
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._days, indent=1))
        return usd

    def spent_today(self) -> float:
        with self._lock:
            return self._days.get(_today(), {}).get("total", 0.0)

    def exhausted(self) -> bool:
        return self.daily_usd > 0 and self.spent_today() >= self.daily_usd
