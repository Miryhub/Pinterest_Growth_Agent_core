import asyncio
import logging
import time
from datetime import datetime, timezone as tz
from apscheduler.schedulers.background import BackgroundScheduler

from src.store.database import Database
from src.brain.seo_scraper import scrape_keywords
from src.brain.trend_monitor import fetch_trends
from src.brain.decision_engine import select_todays_content
from src.creator.image_generator import generate_image
from src.creator.metadata_generator import generate_metadata
from src.creator.quality_gate import check_alignment
from src.worker.scheduler import distribute_posting_times, get_daily_limits
from src.models import Pin
from src.report.cycle_report import CycleReport

logger = logging.getLogger(__name__)


async def run_daily_cycle(db: Database, config: dict, force: bool = False) -> None:
    """
    Phase 2 draft-only cycle.

    This function may research and generate Pin drafts, but it must never log in
    to Pinterest, publish a Pin, scrape Pinterest analytics, or perform any
    browser-based Pinterest action.

    Generated Pins stop at PENDING_REVIEW. Approval and publishing are separate
    workflows added later.
    """
    logger.info("=== Starting draft-only daily cycle ===")
    cycle_start = datetime.now(tz.utc)
    report = CycleReport(cycle_start)

    niche = config.get("niche", {})
    seed_keywords = niche.get("seed_keywords", [])
    categories = niche.get("categories", [])

    try:
        logger.info("Step 1: Research")
        keywords = []
        trends = []

        try:
            keywords = await scrape_keywords(seed_keywords, db, config)
            db.record_scrape_run(
                "seo_scraper",
                success=len(keywords) > 0,
                result_count=len(keywords),
            )
        except Exception as exc:
            logger.warning("SEO scraper failed: %s", exc)
            db.record_scrape_run(
                "seo_scraper", success=False, result_count=0, error=str(exc)
            )

        try:
            trends = await fetch_trends(categories, db, config)
            db.record_scrape_run(
                "trend_monitor",
                success=len(trends) > 0,
                result_count=len(trends),
            )
        except Exception as exc:
            logger.warning("Trend monitor failed: %s", exc)
            db.record_scrape_run(
                "trend_monitor", success=False, result_count=0, error=str(exc)
            )

        report.keywords_found = len(keywords)
        report.trends_found = len(trends)

        logger.info("Step 2: Build content briefs")
        created_date_str = config.get("account", {}).get("created_date", "2026-04-24")
        created_date = datetime.strptime(created_date_str, "%Y-%m-%d")
        limits = get_daily_limits(created_date)
        seo_percent = config.get("strategy", {}).get("seo_percent", 70)

        existing_pin_keywords = db.get_existing_pin_keywords()
        available_keywords = [
            keyword
            for keyword in keywords
            if keyword.term.strip().lower() not in existing_pin_keywords
        ]

        skipped_existing = len(keywords) - len(available_keywords)
        if skipped_existing:
            logger.info(
                "Skipped %s keyword candidates already represented by existing Pins",
                skipped_existing,
            )

        briefs = select_todays_content(
            available_keywords,
            trends,
            limits.max_pins,
            seo_percent,
        )
        report.briefs_created = len(briefs)

        if not briefs:
            db.log_action("draft_cycle_skip", {"reason": "no_briefs"})
            logger.warning("No content briefs generated.")
            return

        logger.info("Step 3: Generate drafts for human review")
        peak_hours = config.get("schedule", {}).get("peak_hours", [10, 14, 18, 20])
        tz_name = config.get("schedule", {}).get("timezone", "UTC")
        suggested_times = distribute_posting_times(len(briefs), peak_hours, tz_name)

        for index, brief in enumerate(briefs):
            try:
                image_path, image_hash = await generate_image(brief, config)
                report.images_generated += 1

                if db.hash_exists(image_hash):
                    logger.warning(
                        "Duplicate image for '%s'; regenerating once.",
                        brief.target_keyword,
                    )
                    image_path, image_hash = await generate_image(
                        brief, config, retry=True
                    )

                if db.hash_exists(image_hash):
                    db.log_action(
                        "duplicate_image",
                        {"keyword": brief.target_keyword, "hash": image_hash},
                    )
                    continue

                metadata = await generate_metadata(brief, config)
                image_prompt = (
                    f"Pinterest travel pin style, {brief.target_keyword}, "
                    "professional photography, 2:3 vertical, clean composition"
                )

                if not await check_alignment(brief, metadata, image_prompt):
                    db.log_action(
                        "quality_gate_failed",
                        {"keyword": brief.target_keyword},
                    )
                    continue

                pin = Pin(
                    image_path=image_path,
                    image_hash=image_hash,
                    title=metadata.title,
                    description=metadata.description,
                    alt_text=metadata.alt_text,
                    target_keyword=brief.target_keyword,
                    board_name=metadata.suggested_board or brief.board_name,
                    content_type=brief.content_type,
                    status="PENDING_REVIEW",
                    scheduled_at=(
                        suggested_times[index]
                        if index < len(suggested_times)
                        else None
                    ),
                )
                pin_id = db.insert_pin(pin)
                db.log_action(
                    "draft_created",
                    {
                        "pin_id": pin_id,
                        "status": "PENDING_REVIEW",
                        "keyword": brief.target_keyword,
                    },
                )
                logger.info(
                    "Draft Pin %s created with status PENDING_REVIEW", pin_id
                )

            except Exception as exc:
                logger.error(
                    "Error creating draft for '%s': %s",
                    brief.target_keyword,
                    exc,
                )
                db.log_action(
                    "draft_error",
                    {"keyword": brief.target_keyword, "error": str(exc)},
                )

    finally:
        report.finish()
        try:
            report.print_summary()
            report.print_file_report()
        except Exception as exc:
            logger.warning("Failed to generate cycle report: %s", exc)

    logger.info(
        "=== Draft-only cycle complete. No Pinterest publication was attempted. ==="
    )


def start_scheduler(config: dict) -> None:
    """
    Start the Phase 2 draft scheduler.

    The scheduled job can only generate PENDING_REVIEW drafts. It has no
    publishing client and no Pinterest credentials path.
    """
    scheduler = BackgroundScheduler(
        timezone=config.get("schedule", {}).get("timezone", "UTC")
    )
    db = Database(config["paths"]["database"])
    db.initialize()

    start_hour = config.get("schedule", {}).get("start_hour", 8)
    def scheduled_draft_cycle() -> None:
        asyncio.run(run_daily_cycle(db, config))

    scheduler.add_job(
        scheduled_draft_cycle,
        "cron",
        hour=start_hour,
        minute=0,
        id="daily_draft_cycle",
        name="BookingsBeacon Pinterest Draft Cycle",
    )

    scheduler.start()
    logger.info(
        "Draft scheduler started. Draft generation runs at %02d:00.", start_hour
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down draft scheduler...")
        scheduler.shutdown()
