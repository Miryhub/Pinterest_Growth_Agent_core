from pathlib import Path


def test_orchestrator_has_no_pinterest_publisher_path():
    source = Path("src/orchestrator.py").read_text(encoding="utf-8")

    forbidden = [
        "PinterestClient",
        "post_pin(",
        "check_pin_visibility(",
        "scrape_engagement(",
    ]

    for token in forbidden:
        assert token not in source, f"Automatic Pinterest path reintroduced: {token}"


def test_orchestrator_stops_at_pending_review():
    source = Path("src/orchestrator.py").read_text(encoding="utf-8")

    assert 'status="PENDING_REVIEW"' in source
    assert "No Pinterest publication was attempted" in source
