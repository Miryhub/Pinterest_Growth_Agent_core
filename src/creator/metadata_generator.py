import logging

from src.models import ContentBrief, PinMetadata

logger = logging.getLogger(__name__)


def _topic_name(keyword: str) -> str:
    text = keyword.strip()
    for suffix in (" travel guide", " guide"):
        if text.lower().endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def _board_for(topic: str) -> str:
    lower = topic.lower()
    if any(city in lower for city in ("marrakech", "agadir", "taghazout", "essaouira", "dakhla", "morocco")):
        return "Morocco Travel"
    if any(city in lower for city in ("paris", "barcelona", "rome", "lisbon", "london", "amsterdam", "istanbul")):
        return "Europe Travel"
    if any(city in lower for city in ("bali", "dubai", "tokyo")):
        return "Asia Travel"
    return "Travel Guides"


async def generate_metadata(brief: ContentBrief, config: dict) -> PinMetadata:
    """
    Phase 2 local metadata generator used to validate the review workflow
    without any external text-model API key.
    """
    topic = _topic_name(brief.target_keyword)
    title = f"{topic}: practical travel guide"

    description = (
        f"Plan your trip to {topic} with practical ideas on where to stay, "
        f"what to do, when to go, and how to make the most of your visit. "
        f"Explore more travel planning inspiration on BookingsBeacon. "
        f"#Travel #TravelGuide #{topic.replace(' ', '')}"
    )

    alt_text = (
        f"Travel inspiration for {topic}, prepared for a BookingsBeacon Pinterest guide."
    )

    return PinMetadata(
        title=title[:100],
        description=description[:500],
        alt_text=alt_text[:500],
        suggested_board=_board_for(topic),
        hashtags=["#Travel", "#TravelGuide", f"#{topic.replace(' ', '')}"],
        destination_link_mode="none",
        default_destination_link="",
    )
