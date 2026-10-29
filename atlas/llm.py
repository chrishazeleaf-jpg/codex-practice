"""
Model access for every ATLAS agent.

ForgeClient is the one choke point: it waits while the daily budget is spent,
turns on prompt caching and refusal fallbacks for live calls, and records cost.
OfflineClient is a scripted stand-in so the whole forge runs without an API key.
"""
import json
import logging
import re
import threading
import time
from types import SimpleNamespace

from .budget import Budget

log = logging.getLogger("LLM")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


class RefusalError(RuntimeError):
    pass


def make_client(budget: Budget, offline: bool = False, api_key: str = None) -> "ForgeClient":
    if offline:
        return ForgeClient(OfflineClient(), budget, live=False)
    import anthropic
    raw = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    return ForgeClient(raw, budget, live=True)


class ForgeClient:
    def __init__(self, raw, budget: Budget, live: bool):
        self.raw = raw
        self.budget = budget
        self.live = live

    def create(self, *, model, max_tokens, system, messages, tools=None, effort=None):
        self._wait_for_budget()
        kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools

        if self.live:
            extra = {"cache_control": {"type": "ephemeral"}}
            if effort:
                extra["output_config"] = {"effort": effort}
            if model in FALLBACK_MODELS:
                extra["fallbacks"] = "default"
                resp = self.raw.beta.messages.create(betas=[FALLBACK_BETA], extra_body=extra, **kwargs)
            else:
                resp = self.raw.messages.create(extra_body=extra, **kwargs)
        else:
            resp = self.raw.messages.create(**kwargs)

        self.budget.record(model, getattr(resp, "usage", None), threading.current_thread().name)
        if getattr(resp, "stop_reason", None) == "refusal":
            details = getattr(resp, "stop_details", None)
            raise RefusalError(f"model declined ({getattr(details, 'category', None)}): "
                               f"{getattr(details, 'explanation', '')}")
        return resp

    def _wait_for_budget(self):
        warned = False
        while self.budget.exhausted():
            if not warned:
                log.warning(f"Daily budget ${self.budget.daily_usd:.2f} spent — "
                            f"{threading.current_thread().name} paused until the UTC day rolls over")
                warned = True
            time.sleep(60)


def extract_json(text: str) -> str:
    if "```json" in text:
        return text.rsplit("```json", 1)[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()


def text_of(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def sources_of(resp) -> list:
    urls = []
    for b in resp.content:
        for c in getattr(b, "citations", None) or []:
            url = getattr(c, "url", None)
            if url and url not in urls:
                urls.append(url)
    return urls


# ---------------------------------------------------------------- offline

_IDEAS = [
    ("Add persistent long-term memory store",
     "Store conversation summaries and learned facts in SQLite so ATLAS remembers across restarts.",
     "HIGH", ["memory", "core systems"]),
    ("Add local model backend via Ollama",
     "Let agents route cheap calls to a local model served by Ollama.",
     "HIGH", ["api integration", "local ai"]),
    ("Add engineer health watchdog",
     "Detect engineers stuck on one order too long and escalate to the Director.",
     "MEDIUM", ["self-healing", "debugging"]),
    ("Build live status dashboard",
     "Terminal dashboard showing queue depth, engineer load and recent completions.",
     "LOW", ["ui"]),
]


def _reply(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                           stop_reason="end_turn", usage=None)


class OfflineClient:
    """Scripted stand-in for anthropic.Anthropic. Its answers are canned, not intelligent."""

    def __init__(self):
        self.messages = self
        self._lock = threading.Lock()
        self._next_idea = 0
        self._seen_orders = []
        self._tool_ids = 0

    def create(self, model, max_tokens, system, messages, tools=None, **_):
        with self._lock:
            if system.startswith("You are Blood Hound, the research"):
                return self._research()
            if system.startswith("You are Blood Hound. Create a precise fix"):
                return self._fix(messages[-1]["content"])
            if system.startswith("You are the Forge Director"):
                return self._pick(messages[-1]["content"])
            return self._engineer(messages)

    def _research(self):
        batch = _IDEAS[self._next_idea:self._next_idea + 2]
        self._next_idea += len(batch)
        orders = [{"title": t, "description": d, "priority": p, "tags": tags}
                  for t, d, p, tags in batch]
        return _reply("Offline research notes.\n```json\n" + json.dumps(orders) + "\n```")

    def _fix(self, prompt):
        title = re.search(r"Title: (.+)", prompt).group(1).strip()
        return _reply(json.dumps({
            "title": f"Fix: unblock '{title[:40]}'",
            "description": "Pin a compatible dependency version and add a schema migration step.",
            "priority": "HIGH", "tags": ["fix", "unblock"],
        }))

    def _pick(self, prompt):
        free = re.findall(r"^\s+(FORGE-\d+): specialties=\[(.*?)\]", prompt, re.M)
        tags = re.search(r"Tags: \[(.*?)\]", prompt).group(1).lower()
        for name, specs in free:
            if any(s.strip(" '") and s.strip(" '") in tags for s in specs.split(",")):
                return _reply(json.dumps({"engineer": name, "reason": "specialty match"}))
        return _reply(json.dumps({"engineer": free[0][0], "reason": "first free"}))

    def _tool(self, name, args):
        self._tool_ids += 1
        block = SimpleNamespace(type="tool_use", id=f"toolu_offline_{self._tool_ids}",
                                name=name, input=args)
        return SimpleNamespace(content=[block], stop_reason="tool_use", usage=None)

    def _engineer(self, messages):
        prompt = messages[0]["content"]
        wo_id = re.search(r"ID: (\w+)", prompt).group(1)
        title = re.search(r"Title: (.+)", prompt).group(1).strip()
        if wo_id not in self._seen_orders:
            self._seen_orders.append(wo_id)
        turn = sum(1 for m in messages if m["role"] == "assistant")

        # The second distinct order struggles on its first attempt to exercise self-healing.
        if (self._seen_orders.index(wo_id) == 1 and "Research from Blood Hound" not in prompt
                and not title.startswith("Fix:")):
            return self._tool("finish", {
                "status": "NEEDS_RESEARCH", "summary": "",
                "struggle": "sqlite3 schema conflicts with the tracker table; need a migration strategy"})
        if turn == 0:
            return self._tool("write_file", {
                "path": f"forge_notes/{wo_id}.md",
                "content": f"# {title}\n\n[offline simulation] placeholder output.\n"})
        return self._tool("finish", {
            "status": "COMPLETE", "struggle": "",
            "summary": f"[offline simulation] wrote forge_notes/{wo_id}.md"})
