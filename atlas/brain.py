"""
ATLAS BRAIN — Central Orchestrator

Brings up all agents, keeps them alive, reports status.
"""
import logging
import time
from typing import List, Optional

from .tracker import WorkOrderTracker
from .bloodhound import BloodHound
from .director import ForgeDirector
from .engineer import Engineer
from .models import WorkOrder, Priority

log = logging.getLogger("BRAIN")


class ATLASBrain:
    def __init__(self, client, model: str = "claude-sonnet-4-6",
                 research_interval_seconds: float = 600):
        self.model = model
        self.tracker = WorkOrderTracker()

        self.engineers: List[Engineer] = [
            Engineer("FORGE-1", self.tracker, client, model=model,
                     specialties=["python", "architecture", "core systems", "agents", "memory"]),
            Engineer("FORGE-2", self.tracker, client, model=model,
                     specialties=["api integration", "web research", "data processing"]),
            Engineer("FORGE-3", self.tracker, client, model=model,
                     specialties=["ui", "debugging", "optimization", "self-healing"]),
        ]
        self.director = ForgeDirector(self.tracker, client, self.engineers, model=model)
        self.bloodhound = BloodHound(self.tracker, client, model=model,
                                     interval_seconds=research_interval_seconds)
        self.director.bloodhound = self.bloodhound

    def start(self):
        log.info("=" * 60)
        log.info("ATLAS BRAIN ONLINE")
        log.info("=" * 60)
        for e in self.engineers:
            e.start()
        self.director.start()
        self.bloodhound.start()
        log.info(f"Auto Forge active: {len(self.engineers)} engineers + director + blood hound")

    def stop(self):
        self.bloodhound.stop()
        self.director.stop()
        for e in self.engineers:
            e.stop()
        log.info("ATLAS shutdown complete")

    def add_work_order(self, title: str, description: str,
                       priority: Priority = Priority.MEDIUM, tags: list = None) -> WorkOrder:
        wo = WorkOrder(title=title, description=description, created_by="user",
                       priority=priority, tags=tags or [])
        self.tracker.save(wo)
        log.info(f"Work order injected: [{wo.id}] {wo.title}")
        return wo

    def status_line(self) -> str:
        wo = self.tracker.stats()
        engines = " ".join(
            f"{e.name}={'BUSY' if e.current_work_order else 'idle'}({e.completed}✓)"
            for e in self.engineers
        )
        return (f"pending={wo.get('pending', 0)} working={wo.get('in_progress', 0)} "
                f"blocked={wo.get('blocked', 0)} done={wo.get('complete', 0)} "
                f"failed={wo.get('failed', 0)} | {engines} | hunts={self.bloodhound.cycles}")

    def run_forever(self, duration: Optional[float] = None, status_every: float = 30):
        self.start()
        deadline = time.monotonic() + duration if duration else None
        next_status = time.monotonic() + status_every
        try:
            while deadline is None or time.monotonic() < deadline:
                time.sleep(0.5)
                if time.monotonic() >= next_status:
                    log.info(f"[STATUS] {self.status_line()}")
                    next_status = time.monotonic() + status_every
        except KeyboardInterrupt:
            print("\nShutting down ATLAS...")
        finally:
            log.info(f"[FINAL] {self.status_line()}")
            self.stop()
