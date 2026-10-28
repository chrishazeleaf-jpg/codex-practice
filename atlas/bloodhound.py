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

import anthropic

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


class BloodHound:
    def __init__(self, tracker: WorkOrderTracker, api_key: str,
                 model: str = "claude-sonnet-4-6", interval_minutes: int = 10):
        self.tracker = tracker
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.interval = interval_minutes * 60
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
        log.info(f"[Blood Hound] Research cycle #{self.cycles}")

        pending_titles = [wo.title for wo in self.tracker.by_status(Status.PENDING)]
        in_progress = [f"{wo.title} (assigned to {wo.assigned_to})"
                       for wo in self.tracker.by_status(Status.IN_PROGRESS)]
        stats = self.tracker.stats()

        prompt = f"""ATLAS current state:
Pending work orders ({len(pending_titles)}):
{chr(10).join(f'  - {t}' for t in pending_titles) or '  (none)'}

In progress ({len(in_progress)}):
{chr(10).join(f'  - {t}' for t in in_progress) or '  (none)'}

Overall stats: {stats}

Hunt for 1-3 HIGH-VALUE improvements. Do not duplicate existing work orders.
Return JSON array only."""

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}]
            )
            text = _extract_json(resp.content[0].text)
            orders = json.loads(text)

            priority_map = {
                "CRITICAL": Priority.CRITICAL, "HIGH": Priority.HIGH,
                "MEDIUM": Priority.MEDIUM, "LOW": Priority.LOW
            }
            created = 0
            for o in orders:
                wo = WorkOrder(
                    title=o["title"],
                    description=o["description"],
                    created_by="bloodhound",
                    priority=priority_map.get(o.get("priority", "MEDIUM"), Priority.MEDIUM),
                    tags=o.get("tags", [])
                )
                self.tracker.save(wo)
                log.info(f"  [Blood Hound] Created [{wo.id}] {wo.title}")
                created += 1

            return created

        except Exception as e:
            log.error(f"[Blood Hound] Cycle error: {e}")
            return 0

    def research_struggle(self, work_order_id: str, struggle: str) -> Optional[str]:
        """Called by Director when an engineer is stuck. Creates a fix work order."""
        wo = self.tracker.get(work_order_id)
        if not wo:
            return None

        log.info(f"[Blood Hound] Researching struggle on [{work_order_id}]: {struggle[:80]}")

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
            text = _extract_json(resp.content[0].text)
            data = json.loads(text)
            fix = WorkOrder(
                title=data["title"],
                description=data["description"],
                created_by="bloodhound",
                priority=Priority.HIGH,
                parent_id=work_order_id,
                tags=data.get("tags", ["fix", "unblock"])
            )
            self.tracker.save(fix)
            log.info(f"  [Blood Hound] Fix created [{fix.id}] {fix.title}")
            return fix.id

        except Exception as e:
            log.error(f"[Blood Hound] research_struggle error: {e}")
            return None

    def _loop(self):
        # Run first cycle immediately on start
        self.run_cycle()
        elapsed = 0
        while self._running:
            time.sleep(1)
            elapsed += 1
            if elapsed >= self.interval:
                self.run_cycle()
                elapsed = 0


def _extract_json(text: str) -> str:
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()
