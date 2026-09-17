from pathlib import Path

import pytest

from src.models import Pin
from src.publisher.pinterest_api import PinterestSandboxPublisher
from src.store.database import Database


def make_db(tmp_path: Path) -> Database:
    db = Database(str(tmp_path / "publisher.db"))
    db.initialize()
    return db


def add_pin(db: Database, status: str) -> int:
    return db.insert_pin(
        Pin(
            image_path="assets/test.png",
            image_hash=f"publisher-{status}",
            title="Paris Travel Guide",
            description="Paris travel description",
            alt_text="Paris travel image",
            target_keyword="Paris travel guide",
            board_name="Europe Travel",
            status=status,
        )
    )


@pytest.mark.asyncio
async def test_publisher_disabled_by_default(tmp_path: Path):
    db = make_db(tmp_path)
    pin_id = add_pin(db, "APPROVED")
    publisher = PinterestSandboxPublisher(
        db,
        {
            "publishing": {
                "enabled": False,
                "environment": "sandbox",
                "api_base_url": "https://api-sandbox.pinterest.com/v5",
            }
        },
    )

    with pytest.raises(RuntimeError, match="disabled"):
        await publisher.publish(pin_id)


@pytest.mark.asyncio
async def test_publisher_rejects_non_approved_pin(tmp_path: Path):
    db = make_db(tmp_path)
    pin_id = add_pin(db, "PENDING_REVIEW")
    publisher = PinterestSandboxPublisher(
        db,
        {
            "publishing": {
                "enabled": True,
                "environment": "sandbox",
                "api_base_url": "https://api-sandbox.pinterest.com/v5",
            }
        },
    )

    with pytest.raises(ValueError, match="APPROVED"):
        await publisher.publish(pin_id)


@pytest.mark.asyncio
async def test_publisher_rejects_non_sandbox_environment(tmp_path: Path):
    db = make_db(tmp_path)
    pin_id = add_pin(db, "APPROVED")
    publisher = PinterestSandboxPublisher(
        db,
        {
            "publishing": {
                "enabled": True,
                "environment": "production",
                "api_base_url": "https://api.pinterest.com/v5",
            }
        },
    )

    with pytest.raises(RuntimeError, match="Sandbox"):
        await publisher.publish(pin_id)


@pytest.mark.asyncio
async def test_missing_oauth_credentials_blocks_before_network(tmp_path: Path, monkeypatch):
    db = make_db(tmp_path)
    pin_id = add_pin(db, "APPROVED")
    monkeypatch.delenv("PINTEREST_SANDBOX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("PINTEREST_SANDBOX_BOARD_ID", raising=False)

    publisher = PinterestSandboxPublisher(
        db,
        {
            "publishing": {
                "enabled": True,
                "environment": "sandbox",
                "api_base_url": "https://api-sandbox.pinterest.com/v5",
            }
        },
    )

    with pytest.raises(RuntimeError, match="ACCESS_TOKEN"):
        await publisher.publish(pin_id)
