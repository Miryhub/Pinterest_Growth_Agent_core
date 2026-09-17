from __future__ import annotations

from dataclasses import asdict

from src.models import Pin
from src.store.database import Database

PENDING_REVIEW = "PENDING_REVIEW"
APPROVED = "APPROVED"
REJECTED = "REJECTED"


class ReviewQueue:
    def __init__(self, db: Database):
        self.db = db

    def list_pending(self) -> list[Pin]:
        return self.db.get_pins_by_status(PENDING_REVIEW)

    def show(self, pin_id: int) -> Pin:
        pin = self.db.get_pin(pin_id)
        if pin is None:
            raise ValueError(f"Pin {pin_id} not found")
        return pin

    def approve(self, pin_id: int) -> Pin:
        pin = self.show(pin_id)
        if pin.status != PENDING_REVIEW:
            raise ValueError(
                f"Pin {pin_id} must be {PENDING_REVIEW} before approval; current status is {pin.status}"
            )
        self.db.update_pin_fields(pin_id, status=APPROVED)
        self.db.log_action("pin_approved", {"pin_id": pin_id})
        return self.show(pin_id)

    def reject(self, pin_id: int) -> Pin:
        pin = self.show(pin_id)
        if pin.status != PENDING_REVIEW:
            raise ValueError(
                f"Pin {pin_id} must be {PENDING_REVIEW} before rejection; current status is {pin.status}"
            )
        self.db.update_pin_fields(pin_id, status=REJECTED)
        self.db.log_action("pin_rejected", {"pin_id": pin_id})
        return self.show(pin_id)

    def edit(
        self,
        pin_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        alt_text: str | None = None,
        board_name: str | None = None,
    ) -> Pin:
        pin = self.show(pin_id)
        if pin.status not in {PENDING_REVIEW, APPROVED}:
            raise ValueError(
                f"Pin {pin_id} cannot be edited while status is {pin.status}"
            )

        changes = {
            key: value
            for key, value in {
                "title": title,
                "description": description,
                "alt_text": alt_text,
                "board_name": board_name,
            }.items()
            if value is not None
        }
        if not changes:
            return pin

        # Any edit after approval must return to human review.
        changes["status"] = PENDING_REVIEW
        self.db.update_pin_fields(pin_id, **changes)
        self.db.log_action(
            "pin_edited",
            {"pin_id": pin_id, "fields": sorted(k for k in changes if k != "status")},
        )
        return self.show(pin_id)

    @staticmethod
    def to_dict(pin: Pin) -> dict:
        return asdict(pin)
