import logging

from src.models import Keyword
from src.store.database import Database

logger = logging.getLogger(__name__)


def _expand_seed(seed: str) -> list[str]:
    """
    Build a small deterministic editorial keyword set from an approved
    BookingsBeacon seed. No Pinterest scraping or browser automation.
    """
    base = seed.strip()
    if not base:
        return []

    topic = base
    for suffix in (" travel guide", " guide"):
        if topic.lower().endswith(suffix):
            topic = topic[: -len(suffix)].strip()
            break

    candidates = [
        base,
        f"best things to do in {topic}",
        f"where to stay in {topic}",
        f"best time to visit {topic}",
        f"{topic} travel tips",
    ]

    seen = set()
    result = []
    for candidate in candidates:
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


async def scrape_keywords(
    seed_keywords: list[str],
    db: Database,
    config: dict,
) -> list[Keyword]:
    """
    Phase 2 safe research provider.

    Uses only the approved BookingsBeacon editorial seed list from config.yaml.
    It does not access Pinterest and does not scrape any external website.
    """
    all_keywords: list[Keyword] = []
    seen = set()

    for seed in seed_keywords:
        for rank, term in enumerate(_expand_seed(seed), start=1):
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)

            keyword = Keyword(
                term=term,
                suggestion_rank=rank,
                related_terms=[seed],
                source="bookingsbeacon_editorial",
            )
            db.upsert_keyword(keyword)
            all_keywords.append(keyword)

    logger.info(
        "Prepared %s BookingsBeacon editorial keyword candidates",
        len(all_keywords),
    )
    return all_keywords
