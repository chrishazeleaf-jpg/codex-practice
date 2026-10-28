"""
FORGE DIRECTOR — ATLAS Work Order Assignment & Monitoring

The Director:
  - Assigns pending work to the right engineer
  - Monitors in-progress work
  - Detects struggles and escalates to Blood Hound
  - Ensures nothing is abandoned — ever
"""
import json
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Optional, List

import anthropic

from .models import WorkOrder, Status
from .tracker import WorkOrderTracker

log = logging.getLogger("DIRECTOR")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json(text: str) -> str:
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()


class ForgeDirector:
    def __init__(self, tracker: WorkOrderTracker, api_key: str,
                 engineers: list, model: str = "claude-sonnet-4-6"):
        self.tracker = tracker
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.engineers = engineers
        self.bloodhound = None  # injected by Brain after construction
        self.assigned = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="Director"
        )
        self._thread.start()
        log.info("[Director] Forge Director ONLINE")

    def stop(self):
        self._running = False

    def select_engineer(self, wo: WorkOrder) -> str:
        """Use AI to pick the best engineer. Falls back to first free engineer."""
        free = [e for e in self.engineers if not e.current_work_order]
        if not free:
            return self.engineers[0].name

        if len(free) == 1:
            return free[0].name

        roster = "\n".join(
            f"  {e.name}: specialties={e.specialties}, completed={e.completed}"
            for e in free
        )
        prompt = f"""Work Order:
  Title: {wo.title}
  Tags: {wo.tags}
  Priority: {wo.priority.name}
  Description (first 300 chars): {wo.description[:300]}

Free Engineers:
{roster}

Select the best engineer. Return JSON only:
{{"engineer": "<name>", "reason": "<one sentence>"}}"""

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=150,
                system="You are the Forge Director. Match work orders to the best engineer.",
                messages=[{"role": "user", "content": prompt}]
            )
            data = json.loads(_extract_json(resp.content[0].text))
            chosen = data.get("engineer", "")
            if any(e.name == chosen for e in free):
                log.info(f"  [Director] {chosen} ← [{wo.id}] ({data.get('reason','')})")
                return chosen
        except Exception as e:
            log.debug(f"[Director] select_engineer fallback: {e}")

        return free[0].name

    def _assign_pending(self):
        pending = self.tracker.by_status(Status.PENDING)
        busy = {e.name for e in self.engineers if e.current_work_order}

        for wo in pending:
            free = [e for e in self.engineers if e.name not in busy]
            if not free:
                break

            engineer_name = self.select_engineer(wo)
            engineer = next((e for e in free if e.name == engineer_name), free[0])

            wo.status = Status.IN_PROGRESS
            wo.assigned_to = engineer.name
            wo.started_at = _now()
            self.tracker.save(wo)
            busy.add(engineer.name)
            self.assigned += 1
            log.info(f"[Director] ➜ [{wo.id}] {wo.title[:50]} → {engineer.name}")

    def _handle_struggles(self):
        """Escalate NEEDS_RESEARCH orders to Blood Hound."""
        struggling = self.tracker.by_status(Status.NEEDS_RESEARCH)
        for wo in struggling:
            if not self.bloodhound:
                continue
            log.warning(f"[Director] Escalating [{wo.id}] to Blood Hound")
            last_struggle = wo.struggles[-1] if wo.struggles else "Unknown"
            fix_id = self.bloodhound.research_struggle(wo.id, last_struggle)
            if fix_id:
                # Re-queue the original order — it will be reassigned after the fix
                wo.status = Status.PENDING
                wo.assigned_to = None
                self.tracker.save(wo)

    def _loop(self):
        while self._running:
            try:
                self._assign_pending()
                self._handle_struggles()
            except Exception as e:
                log.error(f"[Director] Loop error: {e}")
            time.sleep(4)
