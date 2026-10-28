#!/usr/bin/env python3
"""
ATLAS — Autonomous Intelligence & Learning Architecture System
Auto Forge: Blood Hound + Forge Director + Engineers running 24/7
"""
import os
import sys
import logging
import argparse

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║    ░█████╗░████████╗██╗      █████╗ ███████╗               ║
║    ██╔══██╗╚══██╔══╝██║     ██╔══██╗██╔════╝               ║
║    ███████║   ██║   ██║     ███████║███████╗               ║
║    ██╔══██║   ██║   ██║     ██╔══██║╚════██║               ║
║    ██║  ██║   ██║   ███████╗██║  ██║███████║               ║
║    ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚══════╝               ║
║                                                              ║
║    Autonomous Intelligence & Learning Architecture System    ║
║    Auto Forge v1.0 — Always Building. Always Improving.      ║
╚══════════════════════════════════════════════════════════════╝
"""


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)-10s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("atlas_data/atlas.log", mode="a")
        ]
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("\n  ERROR: ANTHROPIC_API_KEY not set.\n")
        print("  Set it with:")
        print("    export ANTHROPIC_API_KEY=sk-ant-...")
        print("  Then run:  python atlas_app.py\n")
        sys.exit(1)
    return key


def cmd_run(args):
    """Start the Auto Forge and run forever."""
    import os
    os.makedirs("atlas_data", exist_ok=True)
    setup_logging(args.verbose)
    print(BANNER)

    api_key = get_api_key()
    model = args.model or "claude-sonnet-4-6"
    interval = args.interval or 10

    print(f"  Model:             {model}")
    print(f"  Research interval: every {interval} minutes")
    print(f"  Engineers:         FORGE-1, FORGE-2, FORGE-3")
    print(f"  Log file:          atlas_data/atlas.log")
    print()
    print("  Starting Auto Forge...")
    print()

    from atlas.brain import ATLASBrain
    brain = ATLASBrain(api_key=api_key, model=model,
                       research_interval_minutes=interval)
    brain.run_forever()


def cmd_status(args):
    """Show current ATLAS status without starting agents."""
    import os
    os.makedirs("atlas_data", exist_ok=True)
    from atlas.tracker import WorkOrderTracker
    from atlas.models import Status

    tracker = WorkOrderTracker()
    stats = tracker.stats()
    all_orders = tracker.all()

    print(BANNER)
    print("  WORK ORDER STATUS")
    print("  " + "─" * 50)
    total = sum(stats.values())
    for status in Status:
        count = stats.get(status.value, 0)
        bar = "█" * count + "░" * max(0, 10 - count)
        print(f"  {status.value:>16}  {bar}  {count}")
    print(f"  {'TOTAL':>16}  {'':10}  {total}")
    print()

    recent = all_orders[:10]
    if recent:
        print("  RECENT WORK ORDERS")
        print("  " + "─" * 50)
        for wo in recent:
            icon = {"pending": "⏳", "in_progress": "⚙", "complete": "✓",
                    "needs_research": "⚠", "failed": "✗"}.get(wo.status.value, "?")
            assigned = f" → {wo.assigned_to}" if wo.assigned_to else ""
            print(f"  {icon} [{wo.id}] {wo.title[:50]}{assigned}")
    print()


def cmd_add(args):
    """Add a work order manually."""
    import os
    os.makedirs("atlas_data", exist_ok=True)
    from atlas.tracker import WorkOrderTracker
    from atlas.models import WorkOrder, Priority

    tracker = WorkOrderTracker()
    priority_map = {"critical": Priority.CRITICAL, "high": Priority.HIGH,
                    "medium": Priority.MEDIUM, "low": Priority.LOW}
    priority = priority_map.get(args.priority.lower(), Priority.MEDIUM)

    wo = WorkOrder(
        title=args.title,
        description=args.description,
        created_by="user",
        priority=priority,
        tags=args.tags.split(",") if args.tags else []
    )
    tracker.save(wo)
    print(f"\n  Work order created: [{wo.id}] {wo.title}")
    print(f"  Priority: {priority.name}")
    print(f"  Run 'python atlas_app.py run' to process it.\n")


def cmd_orders(args):
    """List all work orders."""
    import os
    os.makedirs("atlas_data", exist_ok=True)
    from atlas.tracker import WorkOrderTracker

    tracker = WorkOrderTracker()
    orders = tracker.all()
    if not orders:
        print("\n  No work orders yet. Start the forge: python atlas_app.py run\n")
        return

    status_filter = args.status
    if status_filter:
        orders = [o for o in orders if o.status.value == status_filter]

    print(f"\n  {'ID':>8}  {'PRI':>4}  {'STATUS':>16}  {'ASSIGNED':>8}  TITLE")
    print("  " + "─" * 80)
    for wo in orders:
        assigned = wo.assigned_to or "—"
        print(f"  {wo.id:>8}  {wo.priority.value:>4}  "
              f"{wo.status.value:>16}  {assigned:>8}  {wo.title[:50]}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="ATLAS — Autonomous Intelligence & Learning Architecture System"
    )
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Start the Auto Forge (default)")
    p_run.add_argument("--model", default="claude-sonnet-4-6", help="Anthropic model")
    p_run.add_argument("--interval", type=int, default=10,
                       help="Blood Hound research interval in minutes")
    p_run.add_argument("--verbose", "-v", action="store_true")

    # status
    sub.add_parser("status", help="Show current status (no agents started)")

    # add
    p_add = sub.add_parser("add", help="Add a work order manually")
    p_add.add_argument("title", help="Work order title")
    p_add.add_argument("description", help="Work order description")
    p_add.add_argument("--priority", default="medium",
                       choices=["critical", "high", "medium", "low"])
    p_add.add_argument("--tags", default="", help="Comma-separated tags")

    # orders
    p_orders = sub.add_parser("orders", help="List work orders")
    p_orders.add_argument("--status", help="Filter by status")

    args = parser.parse_args()

    if not args.command or args.command == "run":
        if not args.command:
            args.verbose = False
            args.model = "claude-sonnet-4-6"
            args.interval = 10
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "orders":
        cmd_orders(args)


if __name__ == "__main__":
    main()
