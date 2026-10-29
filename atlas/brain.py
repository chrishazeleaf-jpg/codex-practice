"""
ATLAS BRAIN — Central Orchestrator

Brings up the Forge, the engineers, the Director and Blood Hound, and reports status.
"""
import logging
import time
from pathlib import Path
from typing import List, Optional

from .bloodhound import BloodHound
from .director import ForgeDirector
from .engineer import Engineer
from .models import WorkOrder, Priority
from .tracker import WorkOrderTracker
from .workspace import Forge

log = logging.getLogger("BRAIN")


class ATLASBrain:
    def __init__(self, client, model: str = "claude-opus-5-5",
                 research_interval_seconds: float = 600, repo_root=".",
                 data_dir=Path("atlas_data"), push: bool = False, poll: float = 2.0):
        data_dir = Path(data_dir)
        self.client = client
        self.model = model
        self.tracker = WorkOrderTracker(data_dir / "work_orders.db")
        self.forge = Forge(repo_root, data_dir=data_dir, push=push)

        roster = [
            ("FORGE-1", ["python", "architecture", "core systems", "agents", "memory"]),
            ("FORGE-2", ["api integration", "web research", "local ai", "data processing"]),
            ("FORGE-3", ["ui", "debugging", "optimization", "self-healing", "testing"]),
        ]
        self.engineers: List[Engineer] = [
            Engineer(name, self.tracker, client, self.forge, specialties=specs, model=model,
                     output_dir=data_dir / "output", poll=poll)
            for name, specs in roster
        ]
        self.director = ForgeDirector(self.tracker, client, self.engineers, model=model, poll=poll)
        self.bloodhound = BloodHound(self.tracker, client, model=model,
                                     interval_seconds=research_interval_seconds,
                                     notes_dir=data_dir / "research")
        self.director.bloodhound = self.bloodhound

    def start(self):
        log.info("=" * 60)
        log.info("ATLAS BRAIN ONLINE")
        log.info("=" * 60)
        log.info(f"Forge: worktrees under {self.forge.trees}, landing on branch {self.forge.branch}")
        for e in self.engineers:
            e.start()
        self.director.start()
        self.bloodhound.start()

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
                f"blocked={wo.get('blocked', 0)} landed={wo.get('complete', 0)} "
                f"failed={wo.get('failed', 0)} | {engines} | hunts={self.bloodhound.cycles} "
                f"| spent today ${self.client.budget.spent_today():.2f}")

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
