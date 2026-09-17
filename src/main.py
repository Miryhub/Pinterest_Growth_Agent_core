import asyncio
import logging
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.orchestrator import run_daily_cycle, start_scheduler
from src.publisher.pinterest_api import PinterestSandboxPublisher
from src.review.queue_service import ReviewQueue
from src.store.database import Database
from src.utils.config import load_config
from src.utils.logger import setup_logging

app = typer.Typer(help="BookingsBeacon Pinterest Phase 2 — draft-first workflow.")
console = Console()
logger = logging.getLogger(__name__)


def get_db() -> Database:
    config = load_config()
    db = Database(config["paths"]["database"])
    db.initialize()
    return db


@app.callback()
def main():
    """BookingsBeacon Pinterest Phase 2."""
    setup_logging()


@app.command()
def start():
    """Start the draft-only scheduler. This never publishes to Pinterest."""
    config = load_config()
    db = Database(config["paths"]["database"])
    db.initialize()
    console.print("[bold green]Starting draft-only scheduler...[/bold green]")
    start_scheduler(config)


@app.command()
def run_now():
    """Generate one draft cycle immediately. This never publishes to Pinterest."""
    config = load_config()
    db = Database(config["paths"]["database"])
    db.initialize()
    console.print("[bold cyan]Generating draft Pins for review...[/bold cyan]")
    asyncio.run(run_daily_cycle(db, config))


@app.command("review-list")
def review_list():
    """List Pins waiting for human review."""
    queue = ReviewQueue(get_db())
    pins = queue.list_pending()

    table = Table(title="BookingsBeacon Pinterest Review Queue")
    table.add_column("ID", justify="right")
    table.add_column("Status")
    table.add_column("Keyword")
    table.add_column("Title")
    table.add_column("Board")

    for pin in pins:
        table.add_row(
            str(pin.id),
            pin.status,
            pin.target_keyword,
            pin.title,
            pin.board_name,
        )

    console.print(table)
    if not pins:
        console.print("[dim]No Pins are waiting for review.[/dim]")


@app.command("review-show")
def review_show(pin_id: int):
    """Show one draft in detail."""
    queue = ReviewQueue(get_db())
    try:
        pin = queue.show(pin_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    body = (
        f"[bold]Status:[/bold] {pin.status}\n"
        f"[bold]Keyword:[/bold] {pin.target_keyword}\n"
        f"[bold]Title:[/bold] {pin.title}\n"
        f"[bold]Description:[/bold] {pin.description}\n"
        f"[bold]Alt text:[/bold] {pin.alt_text}\n"
        f"[bold]Board:[/bold] {pin.board_name}\n"
        f"[bold]Image:[/bold] {pin.image_path}\n"
        f"[bold]Suggested time:[/bold] {pin.scheduled_at or '-'}"
    )
    console.print(Panel(body, title=f"Pin #{pin.id}", expand=False))


@app.command("review-open")
def review_open(pin_id: int):
    """Open the generated Pin image in the default Windows image viewer."""
    queue = ReviewQueue(get_db())
    try:
        pin = queue.show(pin_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    image_path = Path(pin.image_path)
    if not image_path.exists():
        raise typer.BadParameter(f"Image not found: {pin.image_path}")

    try:
        os.startfile(str(image_path.resolve()))
    except AttributeError:
        raise typer.BadParameter("review-open is currently supported on Windows only")

    console.print(
        f"[bold green]Opened image for Pin #{pin.id}.[/bold green] "
        f"{image_path}"
    )


@app.command("review-approve")
def review_approve(pin_id: int):
    """Approve one Pin. Approval does NOT publish it."""
    queue = ReviewQueue(get_db())
    try:
        pin = queue.approve(pin_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    console.print(
        f"[bold green]Pin #{pin.id} approved.[/bold green] "
        "It has NOT been published."
    )


@app.command("review-reject")
def review_reject(pin_id: int):
    """Reject one Pin."""
    queue = ReviewQueue(get_db())
    try:
        pin = queue.reject(pin_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    console.print(f"[bold red]Pin #{pin.id} rejected.[/bold red]")


@app.command("review-edit")
def review_edit(
    pin_id: int,
    title: str | None = typer.Option(None, "--title"),
    description: str | None = typer.Option(None, "--description"),
    alt_text: str | None = typer.Option(None, "--alt-text"),
    board_name: str | None = typer.Option(None, "--board"),
):
    """Edit a Pin and return it to PENDING_REVIEW."""
    queue = ReviewQueue(get_db())
    try:
        pin = queue.edit(
            pin_id,
            title=title,
            description=description,
            alt_text=alt_text,
            board_name=board_name,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    console.print(
        f"[bold yellow]Pin #{pin.id} updated.[/bold yellow] "
        f"Status: {pin.status}"
    )


@app.command("publish-sandbox")
def publish_sandbox(pin_id: int):
    """Publish one APPROVED Pin to Pinterest Sandbox after explicit confirmation."""
    config = load_config()
    db = Database(config["paths"]["database"])
    db.initialize()

    pin = db.get_pin(pin_id)
    if pin is None:
        raise typer.BadParameter(f"Pin {pin_id} not found")
    if pin.status != "APPROVED":
        raise typer.BadParameter(
            f"Pin {pin_id} must be APPROVED before Sandbox publishing; current status is {pin.status}"
        )

    console.print(
        Panel(
            f"[bold]Pin #{pin.id}[/bold]\n"
            f"Title: {pin.title}\n"
            f"Board: {pin.board_name}\n"
            f"Status: {pin.status}\n\n"
            "[yellow]Target: Pinterest Sandbox only[/yellow]",
            title="Publish confirmation",
            expand=False,
        )
    )

    if not typer.confirm("Publish this approved Pin to Pinterest Sandbox?"):
        console.print("[dim]Cancelled. Nothing was published.[/dim]")
        raise typer.Exit()

    publisher = PinterestSandboxPublisher(db, config)
    try:
        ref = asyncio.run(publisher.publish(pin_id))
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise typer.BadParameter(str(exc))

    console.print(
        f"[bold green]Pin #{pin_id} published to Pinterest Sandbox.[/bold green] "
        f"Reference: {ref}"
    )


@app.command()
def stats():
    """Show a small Phase 2 status dashboard."""
    db = get_db()
    recent_pins = db.get_recent_pins(days=7)
    pending = sum(1 for p in recent_pins if p.status == "PENDING_REVIEW")
    approved = sum(1 for p in recent_pins if p.status == "APPROVED")
    rejected = sum(1 for p in recent_pins if p.status == "REJECTED")
    published = sum(1 for p in recent_pins if p.status == "PUBLISHED")
    needs_publish_review = sum(
        1 for p in recent_pins if p.status == "NEEDS_PUBLISH_REVIEW"
    )

    summary_text = (
        f"Pending review: [bold blue]{pending}[/bold blue]\n"
        f"Approved: [bold green]{approved}[/bold green]\n"
        f"Rejected: [bold red]{rejected}[/bold red]\n"
        f"Published: [bold]{published}[/bold]\n"
        f"Needs publish review: [bold yellow]{needs_publish_review}[/bold yellow]"
    )
    console.print(Panel(summary_text, title="BookingsBeacon Phase 2", expand=False))


if __name__ == "__main__":
    app()
