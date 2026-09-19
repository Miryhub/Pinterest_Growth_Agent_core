from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path

import httpx

from src.models import Pin
from src.store.database import Database


class PinterestSandboxPublisher:
    def __init__(self, db: Database, config: dict):
        self.db = db
        self.config = config

    def _settings(self) -> dict:
        return self.config.get("publishing", {})

    def _validate_enabled(self) -> None:
        settings = self._settings()
        if not settings.get("enabled", False):
            raise RuntimeError("Pinterest publishing is disabled in config.yaml")

        if settings.get("environment") != "sandbox":
            raise RuntimeError("Only Pinterest Sandbox publishing is allowed in Phase 2")

        base_url = settings.get("api_base_url", "")
        if "api-sandbox.pinterest.com" not in base_url:
            raise RuntimeError("Publisher is not configured for Pinterest Sandbox")

    def _load_pin(self, pin_id: int) -> Pin:
        pin = self.db.get_pin(pin_id)
        if pin is None:
            raise ValueError(f"Pin {pin_id} not found")
        if pin.status != "APPROVED":
            raise ValueError(
                f"Pin {pin_id} must be APPROVED before publishing; current status is {pin.status}"
            )
        return pin

    def _credentials(self) -> tuple[str, str]:
        token = os.getenv("PINTEREST_SANDBOX_ACCESS_TOKEN", "").strip()
        board_id = os.getenv("PINTEREST_SANDBOX_BOARD_ID", "").strip()
        if not token:
            raise RuntimeError("PINTEREST_SANDBOX_ACCESS_TOKEN is not set")
        if not board_id:
            raise RuntimeError("PINTEREST_SANDBOX_BOARD_ID is not set")
        return token, board_id

    DESTINATION_COUNTRY_SLUGS = {
        "paris": "france",
        "barcelona": "spain",
        "bali": "indonesia",
        "marrakech": "morocco",
        "dubai": "united-arab-emirates",
        "london": "united-kingdom",
        "rome": "italy",
        "lisbon": "portugal",
        "amsterdam": "netherlands",
        "istanbul": "turkiye",
    }

    @classmethod
    def _destination_link(cls, pin: Pin) -> str:
        """Build the canonical BookingsBeacon destination URL for this Pin."""
        keyword = (pin.target_keyword or "").strip().lower()
        for suffix in (" travel guide", " guide"):
            if keyword.endswith(suffix):
                keyword = keyword[: -len(suffix)].strip()
                break

        city_slug = "-".join(
            part for part in keyword.replace("_", " ").split() if part
        )
        if not city_slug:
            return "https://bookingsbeacon.com"

        country_slug = cls.DESTINATION_COUNTRY_SLUGS.get(city_slug)
        if country_slug:
            return (
                "https://bookingsbeacon.com/destinations/"
                f"{country_slug}/{city_slug}"
            )

        return "https://bookingsbeacon.com/destinations"

    @staticmethod
    def _image_media_source(image_path: str) -> dict:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        mime_type, _ = mimetypes.guess_type(path.name)
        mime_type = mime_type or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")

        return {
            "source_type": "image_base64",
            "content_type": mime_type,
            "data": encoded,
        }

    async def update_link(self, pin_id: int) -> str:
        """Update the destination link for a previously published Sandbox Pin."""
        self._validate_enabled()

        pin = self.db.get_pin(pin_id)
        if pin is None:
            raise ValueError(f"Pin {pin_id} not found")
        if pin.status != "PUBLISHED":
            raise ValueError(
                f"Pin {pin_id} must be PUBLISHED before updating its Sandbox link; "
                f"current status is {pin.status}"
            )

        sandbox_ref = (pin.pinterest_url or "").strip()
        if not sandbox_ref.startswith("sandbox:"):
            raise ValueError(
                f"Pin {pin_id} does not have a Pinterest Sandbox reference"
            )

        pinterest_id = sandbox_ref.split(":", 1)[1].strip()
        if not pinterest_id:
            raise ValueError("Missing Pinterest Sandbox Pin id")

        token, _ = self._credentials()
        settings = self._settings()
        endpoint = (
            settings["api_base_url"].rstrip("/")
            + f"/pins/{pinterest_id}"
        )

        payload = {"link": self._destination_link(pin)}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.patch(
                endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Pinterest Sandbox returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        self.db.log_action(
            "sandbox_link_updated",
            {
                "pin_id": pin_id,
                "pinterest_id": pinterest_id,
                "link": payload["link"],
            },
        )
        return payload["link"]

    async def publish(self, pin_id: int) -> str:
        self._validate_enabled()
        pin = self._load_pin(pin_id)
        token, board_id = self._credentials()

        settings = self._settings()
        endpoint = settings["api_base_url"].rstrip("/") + "/pins"

        payload = {
            "board_id": board_id,
            "title": pin.title[:100],
            "description": pin.description[:500],
            "alt_text": pin.alt_text[:500],
            "link": self._destination_link(pin),
            "media_source": self._image_media_source(pin.image_path),
        }

        # Lock this Pin before the network request so a second command cannot
        # accidentally submit the same approved draft concurrently.
        self.db.update_pin_fields(pin_id, status="PUBLISHING")
        self.db.log_action("sandbox_publish_started", {"pin_id": pin_id})

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Pinterest Sandbox returned HTTP {response.status_code}: {response.text[:300]}"
                )

            data = response.json()
            pinterest_id = str(data.get("id", "")).strip()
            if not pinterest_id:
                raise RuntimeError("Pinterest Sandbox response did not include a Pin id")

            sandbox_ref = f"sandbox:{pinterest_id}"
            self.db.update_pin_posted(
                pin_id,
                "PUBLISHED",
                sandbox_ref,
                "sandbox_publish",
                {"pin_id": pin_id, "pinterest_id": pinterest_id},
            )
            return sandbox_ref

        except Exception as exc:
            # Do not automatically retry an uncertain network/API failure.
            # Human review is required before another publish attempt.
            self.db.update_pin_fields(pin_id, status="NEEDS_PUBLISH_REVIEW")
            self.db.log_action(
                "sandbox_publish_uncertain",
                {"pin_id": pin_id, "error": str(exc)},
            )
            raise
