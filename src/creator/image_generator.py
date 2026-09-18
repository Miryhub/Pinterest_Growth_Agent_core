import hashlib
import io
import json
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from src.models import ContentBrief

logger = logging.getLogger(__name__)


CURATED_DESTINATION_IMAGES = {
    "paris": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1499856871958-5b9627545d1a?auto=format&fit=crop&w=1800&q=88",
    },
    "barcelona": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1539037116277-4db20889f2d4?auto=format&fit=crop&w=1800&q=88",
    },
    "bali": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1537953773345-d172ccf13cf1?auto=format&fit=crop&w=1800&q=88",
    },
    "marrakech": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1597212618440-806262de4f6b?auto=format&fit=crop&w=1800&q=88",
    },
    "dubai": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1512453979798-5ea266f8880c?auto=format&fit=crop&w=1800&q=88",
    },
    "london": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?auto=format&fit=crop&w=1800&q=88",
    },
    "rome": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1552832230-c0197dd311b5?auto=format&fit=crop&w=1800&q=88",
    },
    "lisbon": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1555881400-74d7acaacd8b?auto=format&fit=crop&w=1800&q=88",
    },
    "amsterdam": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1534351590666-13e3e96b5017?auto=format&fit=crop&w=1800&q=88",
    },
    "istanbul": {
        "provider": "Unsplash",
        "source_url": "https://images.unsplash.com/photo-1524231757912-21f4fe3a7200?auto=format&fit=crop&w=1800&q=88",
    },
}


def _find_curated_source(keyword: str) -> tuple[str, dict] | None:
    lower = keyword.lower()
    for destination, source in CURATED_DESTINATION_IMAGES.items():
        if destination in lower:
            return destination, source
    return None


async def _download_and_crop(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    with Image.open(io.BytesIO(response.content)) as image:
        image = image.convert("RGB")
        fitted = ImageOps.fit(
            image,
            (1000, 1500),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        output = io.BytesIO()
        fitted.save(output, format="PNG", optimize=True)
        return output.getvalue()


def _write_source_metadata(
    image_path: Path,
    *,
    destination: str,
    keyword: str,
    provider: str,
    source_url: str,
) -> None:
    metadata = {
        "destination": destination,
        "keyword": keyword,
        "provider": provider,
        "source_url": source_url,
        "transformation": "center crop and resize to 1000x1500 PNG",
        "usage_note": (
            "Source provenance recorded for review. Verify the provider's current "
            "license/terms and any attribution requirements before publication."
        ),
    }
    metadata_path = image_path.with_suffix(".source.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def generate_image(
    brief: ContentBrief,
    config: dict,
    retry: bool = False,
) -> tuple[str, str]:
    """
    Generate a Pinterest-ready image from an approved real-photo source.

    Phase 2 intentionally refuses unapproved/unknown image sources. There is no
    automatic AI-image fallback here.
    """
    match = _find_curated_source(brief.target_keyword)
    if match is None:
        raise RuntimeError(
            f"No approved real-photo source exists yet for '{brief.target_keyword}'. "
            "Add a reviewed source before generating this Pin."
        )

    destination, source = match
    logger.info(
        "Using approved %s source for '%s'",
        source["provider"],
        brief.target_keyword,
    )

    image_bytes = await _download_and_crop(source["source_url"])
    image_hash = hashlib.sha256(image_bytes).hexdigest()

    assets_dir = Path(config.get("paths", {}).get("assets_dir", "assets"))
    assets_dir.mkdir(parents=True, exist_ok=True)

    image_path = assets_dir / f"{image_hash}.png"
    image_path.write_bytes(image_bytes)

    _write_source_metadata(
        image_path,
        destination=destination,
        keyword=brief.target_keyword,
        provider=source["provider"],
        source_url=source["source_url"],
    )

    logger.info("Prepared curated image: %s", image_path)
    return str(image_path), image_hash
