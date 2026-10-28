"""
ATLAS BRAIN — Central Orchestrator

Brings up all agents, keeps them alive, reports status.
This is the consciousness of ATLAS.
"""
import logging
import time
from typing import List

from .tracker import WorkOrderTracker
from .bloodhound import BloodHound
from .director import ForgeDirector
from .engineer import Engineer
from .models import Status, WorkOrder, Priority

log = logging.getLogger("BRAIN")


class ATLASBrain:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6",
                 research_interval_minutes: int = 10):
        self.api_key = api_key
        self.model = model
        self.tracker = WorkOrderTracker()

        self.engineers: List[Engineer] = [
            Engineer("FORGE-1", self.tracker, api_key, model=model,
                     specialties=["python", "architecture", "core systems", "agents"]),
            Engineer("FORGE-2", self.tracker, api_key, model=model,
                     specialties=["api integration", "web research", "data processing"]),
            Engineer("FORGE-3", self.tracker, api_key, model=model,
                     specialties=["ui", "debugging", "optimization", "self-healing"]),
        ]

        self.director = ForgeDirector(
            self.tracker, api_key, self.engineers, model=model
        )
        self.bloodhound = BloodHound(
            self.tracker, api_key, model=model,
            interval_minutes=research_interval_minutes
        )
        self.director.bloodhound = self.bloodhound
        self._running = False

    def start(self):
        log.info("=" * 60)
        log.info("ATLAS BRAIN ONLINE")
        log.info("=" * 60)
        self._running = True

        for e in self.engineers:
            e.start()
        self.director.start()
        self.bloodhound.start()

        log.info(f"Auto Forge active: {len(self.engineers)} engineers + director + blood hound")

    def stop(self):
        self._running = False
        self.bloodhound.stop()
        self.director.stop()
        for e in self.engineers:
            e.stop()
        log.info("ATLAS shutdown complete")

    def add_work_order(self, title: str, description: str,
                       priority: Priority = Priority.MEDIUM,
                       tags: list = None) -> WorkOrder:
        """Manually inject a work order into the forge."""
        wo = WorkOrder(
            title=title,
            description=description,
            created_by="user",
            priority=priority,
            tags=tags or []
        )
        self.tracker.save(wo)
        log.info(f"[Brain] Work order injected: [{wo.id}] {wo.title}")
        return wo

    def status(self) -> dict:
        stats = self.tracker.stats()
        return {
            "work_orders": stats,
            "total": sum(stats.values()),
            "bloodhound": {
                "cycles": self.bloodhound.cycles,
                "running": self.bloodhound._running
            },
            "director": {
                "assigned": self.director.assigned,
                "running": self.director._running
            },
            "engineers": [
                {
                    "name": e.name,
                    "specialties": e.specialties,
                    "busy": bool(e.current_work_order),
                    "current": e.current_work_order,
                    "completed": e.completed
                }
                for e in self.engineers
            ]
        }

    def run_forever(self):
        """Block and run, printing status every 30s."""
        self.start()
        try:
            tick = 0
            while True:
                time.sleep(30)
                tick += 1
                s = self.status()
                wo = s["work_orders"]
                eng_status = " | ".join(
                    f"{e['name']}={'BUSY' if e['busy'] else 'free'}({e['completed']}✓)"
                    for e in s["engineers"]
                )
                log.info(
                    f"[STATUS #{tick}] "
                    f"pending={wo.get('pending',0)} "
                    f"in_progress={wo.get('in_progress',0)} "
                    f"complete={wo.get('complete',0)} "
                    f"struggling={wo.get('needs_research',0)} | "
                    f"{eng_status} | "
                    f"BH cycles={s['bloodhound']['cycles']}"
                )
        except KeyboardInterrupt:
            print("\nShutting down ATLAS...")
            self.stop()
