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
from src.creator.image_generator import generate_image
from src.models import ContentBrief
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


@app.command("review-regenerate-image")
def review_regenerate_image(pin_id: int):
    """Generate a fresh image for an existing review Pin and keep it in PENDING_REVIEW."""
    config = load_config()
    db = Database(config["paths"]["database"])
    db.initialize()

    pin = db.get_pin(pin_id)
    if pin is None:
        raise typer.BadParameter(f"Pin {pin_id} not found")
    if pin.status not in {"PENDING_REVIEW", "APPROVED"}:
        raise typer.BadParameter(
            f"Pin {pin_id} cannot regenerate image while status is {pin.status}"
        )

    brief = ContentBrief(
        target_keyword=pin.target_keyword,
        content_type=pin.content_type,
        priority=1,
        related_terms=[],
        board_name=pin.board_name,
    )

    image_path, image_hash = asyncio.run(generate_image(brief, config, retry=True))

    if db.hash_exists(image_hash, exclude_pin_id=pin_id):
        raise typer.BadParameter(
            "Another Pin already uses this exact image."
        )

    db.update_pin_fields(
        pin_id,
        image_path=image_path,
        image_hash=image_hash,
        status="PENDING_REVIEW",
    )
    db.log_action(
        "review_image_regenerated",
        {"pin_id": pin_id, "image_path": image_path},
    )

    console.print(
        f"[bold green]Pin #{pin_id} image regenerated.[/bold green] "
        "Status: PENDING_REVIEW"
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



@app.command("sandbox-preflight")
def sandbox_preflight(pin_id: int = typer.Option(1, "--pin-id")):
    """Check Pinterest Sandbox readiness without publishing anything."""
    config = load_config()
    db = Database(config["paths"]["database"])
    db.initialize()

    settings = config.get("publishing", {})
    checks: list[tuple[str, bool, str]] = []

    enabled = bool(settings.get("enabled", False))
    checks.append((
        "Publishing enabled",
        enabled,
        "enabled" if enabled else "disabled in config.yaml",
    ))

    environment = settings.get("environment", "")
    checks.append((
        "Sandbox environment",
        environment == "sandbox",
        environment or "missing",
    ))

    base_url = settings.get("api_base_url", "")
    checks.append((
        "Sandbox API URL",
        "api-sandbox.pinterest.com" in base_url,
        base_url or "missing",
    ))

    token = os.getenv("PINTEREST_SANDBOX_ACCESS_TOKEN", "").strip()
    checks.append((
        "Sandbox access token",
        bool(token),
        "set" if token else "missing",
    ))

    board_id = os.getenv("PINTEREST_SANDBOX_BOARD_ID", "").strip()
    checks.append((
        "Sandbox board ID",
        bool(board_id),
        board_id if board_id else "missing",
    ))

    pin = db.get_pin(pin_id)
    if pin is None:
        checks.append(("Pin exists", False, f"Pin #{pin_id} not found"))
    else:
        checks.append(("Pin exists", True, f"Pin #{pin_id}"))
        checks.append((
            "Pin approved",
            pin.status == "APPROVED",
            pin.status,
        ))
        image_path = Path(pin.image_path)
        checks.append((
            "Pin image exists",
            image_path.exists(),
            str(image_path),
        ))

    table = Table(title="Pinterest Sandbox Preflight")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")

    all_ok = True
    for name, ok, details in checks:
        all_ok = all_ok and ok
        table.add_row(
            name,
            "[green]OK[/green]" if ok else "[red]MISSING[/red]",
            details,
        )

    console.print(table)
    if all_ok:
        console.print(
            "[bold green]Sandbox preflight passed.[/bold green] "
            "Nothing was published."
        )
    else:
        console.print(
            "[bold yellow]Sandbox is not ready yet.[/bold yellow] "
            "Nothing was published."
        )


@app.command("update-sandbox-link")
def update_sandbox_link(pin_id: int):
    """Update the destination link of one already-published Sandbox Pin."""
    config = load_config()
    db = Database(config["paths"]["database"])
    db.initialize()

    publisher = PinterestSandboxPublisher(db, config)
    try:
        link = asyncio.run(publisher.update_link(pin_id))
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise typer.BadParameter(str(exc))

    console.print(
        f"[bold green]Pin #{pin_id} Sandbox link updated.[/bold green] "
        f"{link}"
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
