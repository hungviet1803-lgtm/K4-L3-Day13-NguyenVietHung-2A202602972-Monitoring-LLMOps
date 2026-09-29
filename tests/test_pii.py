from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd() -> None:
    out = scrub_text("CCCD của tôi là 079203001234")
    assert "079203001234" not in out
    assert "REDACTED_CCCD" in out


def test_scrub_credit_card_formats() -> None:
    for card in ("4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"):
        out = scrub_text(f"Card: {card}")
        assert card not in out
        assert "REDACTED_CREDIT_CARD" in out


def test_scrub_passport_vn() -> None:
    out = scrub_text("Passport B1234567")
    assert "B1234567" not in out
    assert "REDACTED_PASSPORT_VN" in out


def test_scrub_multiple_pii_in_one_message() -> None:
    out = scrub_text("Mail a.b+x@gmail.com, phone +84 90 123 4567, card 4111 1111 1111 1111")
    assert "gmail.com" not in out
    assert "4567" not in out
    assert "1111" not in out


def test_scrub_leaves_normal_text() -> None:
    text = "How do I debug tail latency at p95 in 2026?"
    assert scrub_text(text) == text
