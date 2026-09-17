import logging

from src.models import Trend
from src.store.database import Database

logger = logging.getLogger(__name__)


async def fetch_trends(
    categories: list[str],
    db: Database,
    config: dict,
) -> list[Trend]:
    """
    Phase 2 placeholder.

    Trend discovery is deliberately disabled until an approved external trend
    source is connected. This function performs no Pinterest scraping.
    """
    logger.info(
        "Trend discovery disabled in Phase 2; using BookingsBeacon editorial topics only"
    )
    return []
