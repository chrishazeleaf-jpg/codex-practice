import subprocess
import time

from atlas.brain import ATLASBrain
from atlas.budget import Budget, cost_of
from atlas.llm import make_client
from atlas.models import Status


def test_full_loop_offline(git_repo, tmp_path):
    """Research -> assign -> struggle -> fix -> finish -> merge, end to end with the offline model."""
    data = tmp_path / "data"
    client = make_client(Budget(0, data / "spend.json"), offline=True)
    brain = ATLASBrain(client, research_interval_seconds=3600, repo_root=git_repo,
                       data_dir=data, poll=0.1)
    brain.start()
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            stats = brain.tracker.stats()
            if stats.get("complete", 0) == 3 and len(stats) == 1:
                break
            time.sleep(0.2)
    finally:
        brain.stop()

    orders = brain.tracker.all()
    assert {o.status for o in orders} == {Status.COMPLETE}, brain.status_line()
    assert len(orders) == 3

    fix = next(o for o in orders if o.parent_id)
    blocked = brain.tracker.get(fix.parent_id)
    assert blocked.struggles, "the parent order should record the struggle that triggered the fix"

    landed = subprocess.run(["git", "ls-tree", "-r", "--name-only", "atlas-forge", "forge_notes"],
                            cwd=git_repo, capture_output=True, text=True).stdout.split()
    assert sorted(landed) == sorted(f"forge_notes/{o.id}.md" for o in orders)
    assert (data / "output" / f"{blocked.id}.md").exists()
    assert list((data / "research").glob("*.md"))


def test_cost_of_prices_cache_and_search():
    class Usage:
        input_tokens = 1_000_000
        output_tokens = 100_000
        cache_creation_input_tokens = 0
        cache_read_input_tokens = 1_000_000

        class server_tool_use:
            web_search_requests = 3

    assert round(cost_of("claude-opus-5-5", Usage), 4) == round(4.00 + 2.00 + 0.20 + 0.03, 4)


def test_budget_caps_daily_spend(tmp_path):
    class Usage:
        input_tokens = 1_000_000
        output_tokens = 0

    budget = Budget(3.0, tmp_path / "spend.json")
    assert not budget.exhausted()
    budget.record("claude-opus-5-5", Usage, "FORGE-1")
    assert budget.exhausted()
    assert Budget(3.0, tmp_path / "spend.json").spent_today() == 4.0
