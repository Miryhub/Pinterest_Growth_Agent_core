import hashlib
import io
import json
import logging
import textwrap
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.models import ContentBrief

logger = logging.getLogger(__name__)

CANVAS_SIZE = (1000, 1500)
BRAND_MARK_URL = "https://bookingsbeacon.com/beacon-mark.png"

# (horizontal, vertical) focal point used by Pillow ImageOps.fit.
# Higher vertical values keep more of the lower part of a source photo.
SMART_CROP_CENTERING = {
    "paris": (0.50, 0.72),
    "barcelona": (0.50, 0.58),
    "bali": (0.50, 0.50),
    "marrakech": (0.50, 0.54),
    "dubai": (0.50, 0.58),
    "london": (0.50, 0.55),
    "rome": (0.50, 0.56),
    "lisbon": (0.50, 0.56),
    "amsterdam": (0.50, 0.55),
    "istanbul": (0.50, 0.55),
}

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


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/segoeuib.ttf",
                "DejaVuSans-Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
                "DejaVuSans.ttf",
            ]
        )

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _display_title(keyword: str) -> str:
    title = keyword.strip()
    for suffix in (" travel guide", " guide"):
        if title.lower().endswith(suffix):
            title = title[: -len(suffix)].strip()
            break
    return f"{title.title()} Travel Guide"


async def _download_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def _download_and_smart_crop(url: str, destination: str) -> Image.Image:
    raw = await _download_bytes(url)
    centering = SMART_CROP_CENTERING.get(destination, (0.5, 0.5))

    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        return ImageOps.fit(
            image,
            CANVAS_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=centering,
        )


async def _load_brand_mark() -> Image.Image | None:
    try:
        raw = await _download_bytes(BRAND_MARK_URL)
        with Image.open(io.BytesIO(raw)) as mark:
            mark = mark.convert("RGBA")
            mark.thumbnail((82, 82), Image.Resampling.LANCZOS)
            return mark.copy()
    except Exception as exc:
        logger.warning("Could not load BookingsBeacon beacon mark: %s", exc)
        return None


async def _apply_bookingsbeacon_template(
    image: Image.Image,
    keyword: str,
) -> Image.Image:
    canvas = image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))

    # Soft bottom gradient so text remains readable while the photo stays dominant.
    gradient_top = 1050
    gradient_height = CANVAS_SIZE[1] - gradient_top
    for offset in range(gradient_height):
        progress = offset / max(gradient_height - 1, 1)
        alpha = int(18 + (168 * progress))
        ImageDraw.Draw(overlay).line(
            [(0, gradient_top + offset), (CANVAS_SIZE[0], gradient_top + offset)],
            fill=(5, 12, 18, alpha),
            width=1,
        )

    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    title_font = _load_font(64, bold=True)
    small_font = _load_font(30, bold=False)

    title = _display_title(keyword)
    wrapped = textwrap.wrap(title, width=24)
    if len(wrapped) > 2:
        wrapped = wrapped[:2]
    title_text = "\n".join(wrapped)

    title_y = 1190 if len(wrapped) == 1 else 1115
    draw.multiline_text(
        (68, title_y),
        title_text,
        font=title_font,
        fill=(255, 255, 255, 255),
        spacing=8,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 105),
    )

    mark = await _load_brand_mark()
    brand_y = 1400
    brand_x = 68
    if mark is not None:
        mark_y = brand_y - 56
        canvas.alpha_composite(mark, (brand_x, mark_y))
        brand_x += mark.width + 18

    draw = ImageDraw.Draw(canvas)
    draw.text(
        (brand_x, brand_y - 35),
        "bookingsbeacon.com",
        font=small_font,
        fill=(255, 255, 255, 230),
        stroke_width=1,
        stroke_fill=(0, 0, 0, 90),
    )

    return canvas.convert("RGB")


def _write_source_metadata(
    image_path: Path,
    *,
    destination: str,
    keyword: str,
    provider: str,
    source_url: str,
) -> None:
    centering = SMART_CROP_CENTERING.get(destination, (0.5, 0.5))
    metadata = {
        "destination": destination,
        "keyword": keyword,
        "provider": provider,
        "source_url": source_url,
        "smart_crop_centering": list(centering),
        "transformation": (
            "smart crop to 1000x1500, subtle bottom gradient, destination title, "
            "BookingsBeacon beacon mark and bookingsbeacon.com"
        ),
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
    Prepare a branded Pinterest image from an approved real-photo source.

    Phase 2 refuses unknown/unapproved image sources and performs no automatic
    AI-image fallback.
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

    image = await _download_and_smart_crop(source["source_url"], destination)
    image = await _apply_bookingsbeacon_template(image, brief.target_keyword)

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    image_bytes = output.getvalue()
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

    logger.info("Prepared branded curated image: %s", image_path)
    return str(image_path), image_hash
