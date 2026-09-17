import logging

from src.models import ContentBrief, PinMetadata

logger = logging.getLogger(__name__)


async def check_alignment(
    brief: ContentBrief,
    metadata: PinMetadata,
    image_prompt: str,
) -> bool:
    """
    Deterministic Phase 2 quality gate.

    The draft is accepted only when the main keyword/topic is represented in
    the title or description and required metadata fields are present.
    No external model or Pinterest access is used.
    """
    keyword = brief.target_keyword.strip().lower()
    topic = keyword
    for suffix in (" travel guide", " guide"):
        if topic.endswith(suffix):
            topic = topic[: -len(suffix)].strip()
            break

    haystack = " ".join(
        [metadata.title, metadata.description, metadata.alt_text, image_prompt]
    ).lower()

    required_fields_present = all(
        [
            metadata.title.strip(),
            metadata.description.strip(),
            metadata.alt_text.strip(),
            metadata.suggested_board.strip(),
        ]
    )

    aligned = required_fields_present and topic in haystack
    logger.info("Local quality gate for '%s': %s", brief.target_keyword, aligned)
    return aligned
