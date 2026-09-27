"""Logging and console presentation using Rich."""

import logging
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
)

logger = logging.getLogger("job_bot")


def print_jobs_table(jobs: list[dict]):
    """Pretty prints a table of jobs."""
    if not jobs:
        console.print("[yellow]No jobs to display.[/yellow]")
        return

    table = Table(title="💼 Discovered / Processed Job Listings", header_style="bold magenta")
    table.add_column("ID", style="dim", width=12)
    table.add_column("Title", style="bold cyan")
    table.add_column("Company", style="green")
    table.add_column("Salary / LPA", style="yellow")
    table.add_column("Status", style="bold")
    table.add_column("Updated", style="dim")

    for j in jobs:
        salary_display = j.get("salary_raw") or "Not listed"
        if j.get("min_lpa") or j.get("max_lpa"):
            min_l = f"{j['min_lpa']:.1f}" if j.get("min_lpa") else "?"
            max_l = f"{j['max_lpa']:.1f}" if j.get("max_lpa") else "?"
            salary_display += f" ({min_l}-{max_l} LPA)"

        status = j.get("status", "N/A")
        status_color = {
            "APPLIED": "[bold green]APPLIED[/bold green]",
            "QUEUED": "[cyan]QUEUED[/cyan]",
            "DISCOVERED": "[blue]DISCOVERED[/blue]",
            "FILTERED_OUT": "[dim red]FILTERED[/dim red]",
            "FAILED": "[bold red]FAILED[/bold red]",
            "REVIEW_NEEDED": "[bold yellow]REVIEW[/bold yellow]",
            "SKIPPED": "[dim]SKIPPED[/dim]",
        }.get(status, status)

        table.add_row(
            str(j.get("id", ""))[:12],
            str(j.get("title", ""))[:32],
            str(j.get("company", ""))[:20],
            salary_display[:24],
            status_color,
            str(j.get("updated_at", ""))[:19],
        )

    console.print(table)
