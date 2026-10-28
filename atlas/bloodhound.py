"""
BLOOD HOUND — ATLAS Research & Intelligence Agent

Runs continuously. Hunts for improvements. Creates work orders.
When an engineer struggles, Blood Hound finds the fix.
"""
import json
import logging
import time
import threading
from typing import Optional

from .llm import extract_json, text_of
from .models import WorkOrder, Priority, Status
from .tracker import WorkOrderTracker

log = logging.getLogger("BLOODHOUND")

_SYSTEM = """You are Blood Hound, the research and intelligence agent of ATLAS.

ATLAS is an autonomous AI system you are a part of:
  • Blood Hound (you) — research, improvement discovery, fix creation
  • Forge Director — assigns work orders to engineers
  • Engineers (FORGE-1, FORGE-2, FORGE-3) — implement work fully
  • The Forge — execution and build environment

YOUR MISSION: Continuously identify specific, actionable improvements to make ATLAS
smarter, faster, more capable, and more autonomous. Think about:
  - New agent capabilities (deep think, chain-of-thought, memory expansion)
  - Performance bottlenecks and how to remove them
  - New tool integrations (web search, code execution, file I/O)
  - Architecture improvements (better agent communication, parallelism)
  - Self-healing mechanisms (auto-detect failure modes and recover)
  - Knowledge persistence and learning between sessions

Each work order you create MUST be:
  1. Concrete — a single specific thing to implement or fix
  2. Complete — fully describable so an engineer knows exactly what to do
  3. Valuable — meaningfully advances ATLAS

Return a JSON array. Each element:
{
  "title": "short imperative title (max 60 chars)",
  "description": "detailed spec: what, why, how — enough for an engineer to implement without questions",
  "priority": "CRITICAL|HIGH|MEDIUM|LOW",
  "tags": ["tag1", "tag2"]
}

Only return the JSON array. No other text."""

_PRIORITY = {
    "CRITICAL": Priority.CRITICAL, "HIGH": Priority.HIGH,
    "MEDIUM": Priority.MEDIUM, "LOW": Priority.LOW,
}


class BloodHound:
    def __init__(self, tracker: WorkOrderTracker, client,
                 model: str = "claude-sonnet-4-6", interval_seconds: float = 600):
        self.tracker = tracker
        self.client = client
        self.model = model
        self.interval = interval_seconds
        self.cycles = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BloodHound")
        self._thread.start()
        log.info("Blood Hound ON THE HUNT")

    def stop(self):
        self._running = False

    def run_cycle(self) -> int:
        """One research cycle. Returns number of work orders created."""
        self.cycles += 1
        log.info(f"Research cycle #{self.cycles}")

        open_titles = [wo.title for s in (Status.PENDING, Status.IN_PROGRESS, Status.BLOCKED)
                       for wo in self.tracker.by_status(s)]
        recent_done = [wo.title for wo in self.tracker.by_status(Status.COMPLETE)][-15:]

        prompt = f"""ATLAS current state:
Open work orders ({len(open_titles)}):
{chr(10).join(f'  - {t}' for t in open_titles) or '  (none)'}

Recently completed:
{chr(10).join(f'  - {t}' for t in recent_done) or '  (none)'}

Overall stats: {self.tracker.stats()}

Hunt for 1-3 HIGH-VALUE improvements. Do not duplicate existing or completed work orders.
Return JSON array only."""

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}]
            )
            orders = json.loads(extract_json(text_of(resp)))
            for o in orders:
                wo = WorkOrder(
                    title=o["title"],
                    description=o["description"],
                    created_by="bloodhound",
                    priority=_PRIORITY.get(o.get("priority", "MEDIUM"), Priority.MEDIUM),
                    tags=o.get("tags", [])
                )
                self.tracker.save(wo)
                log.info(f"  Created [{wo.id}] {wo.title}")
            if not orders:
                log.info("  Nothing new worth building this cycle")
            return len(orders)

        except Exception as e:
            log.error(f"Cycle error: {e}")
            return 0

    def research_struggle(self, work_order_id: str, struggle: str) -> Optional[str]:
        """Called by the Director when an engineer is stuck. Creates a fix work order."""
        wo = self.tracker.get(work_order_id)
        if not wo:
            return None

        log.info(f"Researching struggle on [{work_order_id}]: {struggle[:80]}")

        prompt = f"""ENGINEER IS STUCK. Find the fix.

Blocked Work Order:
  ID: {wo.id}
  Title: {wo.title}
  Description: {wo.description[:600]}
  Struggle: {struggle}
  Previous struggles: {wo.struggles}

Create ONE specific fix/research work order that will unblock this engineer.
Return a single JSON object (not array):
{{
  "title": "Fix: <what you will resolve>",
  "description": "<exact steps, patches, or research needed to unblock>",
  "priority": "HIGH",
  "tags": ["fix", "unblock"]
}}
JSON only."""

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system="You are Blood Hound. Create a precise fix work order to unblock the engineer.",
                messages=[{"role": "user", "content": prompt}]
            )
            data = json.loads(extract_json(text_of(resp)))
            fix = WorkOrder(
                title=data["title"],
                description=data["description"],
                created_by="bloodhound",
                priority=Priority.HIGH,
                parent_id=work_order_id,
                tags=data.get("tags", ["fix", "unblock"])
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
