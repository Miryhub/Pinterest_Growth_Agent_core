from pathlib import Path

import pytest

from src.models import Pin
from src.review.queue_service import APPROVED, PENDING_REVIEW, REJECTED, ReviewQueue
from src.store.database import Database


def make_db(tmp_path: Path) -> Database:
    db = Database(str(tmp_path / "phase2.db"))
    db.initialize()
    return db


def insert_sample_pin(db: Database, status: str = PENDING_REVIEW) -> int:
    return db.insert_pin(
        Pin(
            image_path="assets/test.png",
            image_hash=f"hash-{status}",
            title="Visit Taghazout",
            description="Sample description",
            alt_text="Taghazout coastline",
            target_keyword="taghazout",
            board_name="Morocco Travel",
            content_type="seo",
            status=status,
        )
    )


def test_approve_only_changes_status_and_does_not_publish(tmp_path: Path):
    db = make_db(tmp_path)
    pin_id = insert_sample_pin(db)

    queue = ReviewQueue(db)
    approved = queue.approve(pin_id)

    assert approved.status == APPROVED
    assert approved.pinterest_url == ""
    assert approved.posted_at is None


def test_reject_marks_pin_rejected(tmp_path: Path):
    db = make_db(tmp_path)
    pin_id = insert_sample_pin(db)

    rejected = ReviewQueue(db).reject(pin_id)

    assert rejected.status == REJECTED


def test_edit_returns_approved_pin_to_pending_review(tmp_path: Path):
    db = make_db(tmp_path)
    pin_id = insert_sample_pin(db)

    queue = ReviewQueue(db)
    queue.approve(pin_id)
    edited = queue.edit(pin_id, title="Better Taghazout Guide")

    assert edited.status == PENDING_REVIEW
    assert edited.title == "Better Taghazout Guide"


def test_cannot_approve_rejected_pin(tmp_path: Path):
    db = make_db(tmp_path)
    pin_id = insert_sample_pin(db)

    queue = ReviewQueue(db)
    queue.reject(pin_id)

    with pytest.raises(ValueError):
        queue.approve(pin_id)
