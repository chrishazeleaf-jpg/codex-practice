"""
FORGE DIRECTOR — ATLAS Work Order Assignment & Monitoring

The Director:
  - Assigns pending work to the right engineer, one order per engineer
  - Escalates struggles to Blood Hound and parks the order as BLOCKED
  - Returns a BLOCKED order to the queue once its fix is complete
  - Fails an order after MAX_STRUGGLES so it surfaces to a human instead of looping
"""
import json
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Optional, List

from .llm import extract_json, text_of
from .models import WorkOrder, Status
from .tracker import WorkOrderTracker

log = logging.getLogger("DIRECTOR")

MAX_STRUGGLES = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ForgeDirector:
    def __init__(self, tracker: WorkOrderTracker, client,
                 engineers: list, model: str = "claude-opus-5-5", poll: float = 2.0):
        self.tracker = tracker
        self.client = client
        self.model = model
        self.engineers = engineers
        self.poll = poll
        self.bloodhound = None
        self.assigned = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Director")
        self._thread.start()
        log.info("Forge Director ONLINE")

    def stop(self):
        self._running = False

    def select_engineer(self, wo: WorkOrder, free: list) -> str:
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
            resp = self.client.create(
                model=self.model,
                max_tokens=2000,
                system="You are the Forge Director. Match work orders to the best engineer.",
                messages=[{"role": "user", "content": prompt}],
                effort="low",
            )
            data = json.loads(extract_json(text_of(resp)))
            chosen = data.get("engineer", "")
            if any(e.name == chosen for e in free):
                return chosen
        except Exception as e:
            log.debug(f"select_engineer fallback: {e}")
        return free[0].name

    def _assign_pending(self):
        # Busy is read from the tracker, not engineer state, so an engineer that
        # hasn't picked up its order yet is never handed a second one.
        busy = {wo.assigned_to for wo in self.tracker.by_status(Status.IN_PROGRESS)}
        for wo in self.tracker.by_status(Status.PENDING):
            free = [e for e in self.engineers if e.name not in busy]
            if not free:
                return
            name = self.select_engineer(wo, free)
            wo.status = Status.IN_PROGRESS
            wo.assigned_to = name
            wo.started_at = _now()
            self.tracker.save(wo)
            busy.add(name)
            self.assigned += 1
            log.info(f"➜ [{wo.id}] {wo.title[:50]} → {name}")

    def _handle_struggles(self):
        for wo in self.tracker.by_status(Status.NEEDS_RESEARCH):
            if len(wo.struggles) >= MAX_STRUGGLES:
                wo.status = Status.FAILED
                self.tracker.save(wo)
                log.error(f"✗ [{wo.id}] failed after {len(wo.struggles)} struggles — needs a human")
                continue
            if not self.bloodhound:
                continue
            log.warning(f"Escalating [{wo.id}] to Blood Hound")
            fix_id = self.bloodhound.research_struggle(wo.id, wo.struggles[-1])
            if fix_id:
                wo.status = Status.BLOCKED
                wo.assigned_to = None
                self.tracker.save(wo)
                log.info(f"⏸ [{wo.id}] BLOCKED until fix [{fix_id}] completes")

    def _release_blocked(self):
        for wo in self.tracker.by_status(Status.BLOCKED):
            fixes = self.tracker.children(wo.id)
            if any(f.status == Status.FAILED for f in fixes):
                wo.status = Status.FAILED
                self.tracker.save(wo)
                log.error(f"✗ [{wo.id}] failed — its fix failed")
            elif fixes and all(f.status == Status.COMPLETE for f in fixes):
                wo.status = Status.PENDING
                self.tracker.save(wo)
                log.info(f"▶ [{wo.id}] fix landed — back in the queue to finish")

    def _loop(self):
        while self._running:
            try:
                self._handle_struggles()
                self._release_blocked()
                self._assign_pending()
            except Exception as e:
                log.error(f"Loop error: {e}")
            time.sleep(self.poll)
