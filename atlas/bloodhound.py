"""
BLOOD HOUND — ATLAS Research & Intelligence Agent

Runs continuously. Searches the live web, writes research notes, and turns what
it finds into work orders. When an engineer struggles, Blood Hound finds the fix.
"""
import json
import logging
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .llm import WEB_SEARCH_TOOL, extract_json, sources_of, text_of
from .models import WorkOrder, Priority, Status
from .tracker import WorkOrderTracker

log = logging.getLogger("BLOODHOUND")

_SYSTEM = """You are Blood Hound, the research and intelligence agent of ATLAS.

ATLAS is one person's AI: a real-time entity for his home, life and family that will
live in his wearables and, one day, a robot body. It runs as a team of agents:
  • Blood Hound (you): research, improvement discovery, fixes for stuck engineers
  • Forge Director: assigns work orders to engineers
  • Engineers (FORGE-1, FORGE-2, FORGE-3): implement work orders in the ATLAS Python repo
  • The Forge: isolated git worktrees, test-gated merges

The long-term aim is an ATLAS that grows its own abilities: local and personal AI
models, memory, tools, voice and wearable integration, self-improvement loops that
spawn new automations, and eventually its own fine-tuned models.

Research the current state of local AI, personal AI assistants and agent frameworks,
self-improving agent techniques, on-device and wearable AI, and anything else that
would make ATLAS more capable. Use web search to ground your findings in current sources.

Then turn the most valuable findings into work orders. Engineers work only inside the
ATLAS repository with file tools and Python, and every order must land with passing
pytest tests that need no network or API key. So each order must be:
  1. One concrete change to this repository, small enough for one engineer session
  2. Specified well enough to implement without questions: what, why, which files, which tests
  3. A real step toward the long-term aim. Break big goals (training models, wearables)
     into repository-sized steps such as interfaces, adapters, evaluation harnesses or data
     pipelines with mocked boundaries.

Write a short research summary, then end with a ```json fenced array of 1-3 work orders:
[{"title": "short imperative title, max 60 chars",
  "description": "detailed spec",
  "priority": "CRITICAL|HIGH|MEDIUM|LOW",
  "tags": ["tag1", "tag2"]}]"""

_FIX_SYSTEM = "You are Blood Hound. Create a precise fix work order to unblock the engineer."

_PRIORITY = {
    "CRITICAL": Priority.CRITICAL, "HIGH": Priority.HIGH,
    "MEDIUM": Priority.MEDIUM, "LOW": Priority.LOW,
}


class BloodHound:
    def __init__(self, tracker: WorkOrderTracker, client, model: str = "claude-opus-5-5",
                 interval_seconds: float = 600, notes_dir: Path = Path("atlas_data/research")):
        self.tracker = tracker
        self.client = client
        self.model = model
        self.interval = interval_seconds
        self.notes_dir = Path(notes_dir)
        self.cycles = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BloodHound")
        self._thread.start()
        log.info("Blood Hound ON THE HUNT" + (" (live web search)" if self.client.live else ""))

    def stop(self):
        self._running = False

    def _ask(self, system: str, prompt: str, tools=None):
        messages = [{"role": "user", "content": prompt}]
        for _ in range(5):
            resp = self.client.create(model=self.model, max_tokens=16000, system=system,
                                      messages=messages, tools=tools, effort="high")
            if getattr(resp, "stop_reason", None) != "pause_turn":
                return resp
            messages.append({"role": "assistant", "content": resp.content})
        return resp

    def run_cycle(self) -> int:
        """One research cycle. Returns number of work orders created."""
        self.cycles += 1
        log.info(f"Research cycle #{self.cycles}")

        open_titles = [wo.title for s in (Status.PENDING, Status.IN_PROGRESS, Status.BLOCKED)
                       for wo in self.tracker.by_status(s)]
        done = [wo.title for wo in self.tracker.by_status(Status.COMPLETE)][-25:]
        failed = [f"{wo.title}: {wo.struggles[-1][:200] if wo.struggles else ''}"
                  for wo in self.tracker.by_status(Status.FAILED)][-10:]

        prompt = f"""ATLAS current state:
Open work orders ({len(open_titles)}):
{chr(10).join(f'  - {t}' for t in open_titles) or '  (none)'}

Completed so far:
{chr(10).join(f'  - {t}' for t in done) or '  (none)'}

Failed (avoid repeating these the same way):
{chr(10).join(f'  - {t}' for t in failed) or '  (none)'}

Hunt for the next 1-3 highest-value improvements. Do not duplicate open or completed work."""

        try:
            tools = [WEB_SEARCH_TOOL] if self.client.live else None
            resp = self._ask(_SYSTEM, prompt, tools)
            text = text_of(resp)
            self._save_notes(text, sources_of(resp))
            orders = json.loads(extract_json(text))
            for o in orders:
                wo = WorkOrder(
                    title=o["title"],
                    description=o["description"],
                    created_by="bloodhound",
                    priority=_PRIORITY.get(o.get("priority", "MEDIUM"), Priority.MEDIUM),
                    tags=o.get("tags", []),
                )
                self.tracker.save(wo)
                log.info(f"  Created [{wo.id}] {wo.title}")
            if not orders:
                log.info("  Nothing new worth building this cycle")
            return len(orders)
        except Exception as e:
            log.error(f"Cycle error: {e}")
            return 0

    def _save_notes(self, text: str, sources: list):
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        body = f"# Research cycle {self.cycles} ({stamp} UTC)\n\n{text}\n"
        if sources:
            body += "\n## Sources\n\n" + "\n".join(f"- {u}" for u in sources) + "\n"
        (self.notes_dir / f"{stamp}-cycle{self.cycles}.md").write_text(body)

    def research_struggle(self, work_order_id: str, struggle: str) -> Optional[str]:
        """Called by the Director when an engineer is stuck. Creates a fix work order."""
        wo = self.tracker.get(work_order_id)
        if not wo:
            return None

        log.info(f"Researching struggle on [{work_order_id}]: {struggle[:80]}")
        prompt = f"""An engineer is stuck. Find the fix.

Blocked work order:
  ID: {wo.id}
  Title: {wo.title}
  Description: {wo.description[:1500]}
  Struggle: {struggle[:3000]}
  Earlier struggles: {[s[:300] for s in wo.struggles[:-1]]}

Create ONE work order that unblocks it: a change to the ATLAS repository that lands
with passing tests. If the blocker can't be solved inside the repository (credentials,
hardware, a paid service), the fix should add the adapter or interface with a mocked
boundary and say plainly in the description what the human must provide.
Return a single JSON object:
{{"title": "Fix: ...", "description": "...", "priority": "HIGH", "tags": ["fix"]}}"""

        try:
            tools = [WEB_SEARCH_TOOL] if self.client.live else None
            data = json.loads(extract_json(text_of(self._ask(_FIX_SYSTEM, prompt, tools))))
            fix = WorkOrder(
                title=data["title"],
                description=data["description"],
                created_by="bloodhound",
                priority=Priority.HIGH,
                parent_id=work_order_id,
                tags=data.get("tags", ["fix"]),
            )
            self.tracker.save(fix)
            log.info(f"  Fix created [{fix.id}] {fix.title}")
            return fix.id
        except Exception as e:
            log.error(f"research_struggle error: {e}")
            return None

    def _loop(self):
        self.run_cycle()
        next_run = time.monotonic() + self.interval
        while self._running:
            time.sleep(0.5)
            if time.monotonic() >= next_run:
                self.run_cycle()
                next_run = time.monotonic() + self.interval
