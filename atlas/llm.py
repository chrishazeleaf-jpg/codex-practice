"""LLM client factory. Offline mode runs the full forge without an API key."""
import json
import re
import threading
from types import SimpleNamespace


def make_client(api_key: str = None, offline: bool = False):
    if offline:
        return OfflineClient()
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def extract_json(text: str) -> str:
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()


def text_of(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", "text") == "text")


class OfflineClient:
    """Scripted stand-in for anthropic.Anthropic. Responses are canned, not intelligent."""

    def __init__(self):
        self.messages = _OfflineMessages()


_IDEAS = [
    ("Add persistent long-term memory store",
     "Store conversation summaries and learned facts in SQLite so ATLAS remembers across restarts.",
     "HIGH", ["memory", "core systems"]),
    ("Add web search tool for Blood Hound",
     "Give Blood Hound a web search tool so research is grounded in current sources.",
     "HIGH", ["web research", "api integration"]),
    ("Add deep-think reasoning mode",
     "Route hard work orders through extended thinking before implementation.",
     "MEDIUM", ["agents", "architecture"]),
    ("Add engineer health watchdog",
     "Detect engineers stuck on one order too long and escalate to the Director.",
     "MEDIUM", ["self-healing", "debugging"]),
    ("Build live status dashboard",
     "Terminal dashboard showing queue depth, engineer load and recent completions.",
     "LOW", ["ui"]),
    ("Add token cost tracking",
     "Record input/output tokens per work order and report spend per agent.",
     "LOW", ["optimization", "data processing"]),
]


class _OfflineMessages:
    def __init__(self):
        self._lock = threading.Lock()
        self._next_idea = 0
        self._seen_orders = []

    def create(self, model, max_tokens, system, messages, **_):
        prompt = messages[-1]["content"]
        with self._lock:
            if system.startswith("You are Blood Hound, the research"):
                text = self._research()
            elif system.startswith("You are Blood Hound. Create a precise fix"):
                text = self._fix(prompt)
            elif system.startswith("You are the Forge Director"):
                text = self._pick(prompt)
            else:
                text = self._engineer(prompt)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    def _research(self):
        batch = _IDEAS[self._next_idea:self._next_idea + 2]
        self._next_idea += len(batch)
        return json.dumps([
            {"title": t, "description": d, "priority": p, "tags": tags}
            for t, d, p, tags in batch
        ])

    def _fix(self, prompt):
        title = re.search(r"Title: (.+)", prompt).group(1).strip()
        return json.dumps({
            "title": f"Fix: unblock '{title[:40]}'",
            "description": "Pin a compatible dependency version and add a schema migration step.",
            "priority": "HIGH",
            "tags": ["fix", "unblock"],
        })

    def _pick(self, prompt):
        free = re.findall(r"^\s+(FORGE-\d+): specialties=\[(.*?)\]", prompt, re.M)
        tags = re.search(r"Tags: \[(.*?)\]", prompt).group(1).lower()
        for name, specs in free:
            if any(s.strip(" '") in tags for s in specs.split(",") if s.strip(" '")):
                return json.dumps({"engineer": name, "reason": "specialty match"})
        return json.dumps({"engineer": free[0][0], "reason": "first free"})

    def _engineer(self, prompt):
        wo_id = re.search(r"ID: (\w+)", prompt).group(1)
        title = re.search(r"Title: (.+)", prompt).group(1).strip()
        if wo_id not in self._seen_orders:
            self._seen_orders.append(wo_id)
        # The second distinct order struggles on its first attempt to exercise self-healing.
        first_attempt = "Research from Blood Hound" not in prompt
        if self._seen_orders.index(wo_id) == 1 and first_attempt and not title.startswith("Fix:"):
            return ("STATUS: NEEDS_RESEARCH\n"
                    "STRUGGLE: sqlite3 schema conflicts with existing tracker table; "
                    "need a migration strategy\nRESULT:\n")
        return (f"STATUS: COMPLETE\nSTRUGGLE:\nRESULT:\n"
                f"[offline simulation] Implemented '{title}'.\n")
