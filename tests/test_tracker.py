from atlas.models import Priority, Status, WorkOrder
from atlas.tracker import WorkOrderTracker


def test_save_get_and_stats(tmp_path):
    tracker = WorkOrderTracker(tmp_path / "wo.db")
    wo = WorkOrder("Build memory", "desc", "test", priority=Priority.HIGH, tags=["memory"])
    tracker.save(wo)

    found = tracker.get(wo.id)
    assert found.title == "Build memory"
    assert found.priority == Priority.HIGH
    assert found.tags == ["memory"]
    assert tracker.stats() == {"pending": 1}


def test_pending_ordered_by_priority(tmp_path):
    tracker = WorkOrderTracker(tmp_path / "wo.db")
    tracker.save(WorkOrder("low", "d", "t", priority=Priority.LOW))
    tracker.save(WorkOrder("critical", "d", "t", priority=Priority.CRITICAL))
    assert [w.title for w in tracker.by_status(Status.PENDING)] == ["critical", "low"]


def test_children(tmp_path):
    tracker = WorkOrderTracker(tmp_path / "wo.db")
    parent = WorkOrder("parent", "d", "t")
    fix = WorkOrder("Fix: x", "d", "t", parent_id=parent.id)
    tracker.save(parent)
    tracker.save(fix)
    assert [c.id for c in tracker.children(parent.id)] == [fix.id]
