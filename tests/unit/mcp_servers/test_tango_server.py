"""Unit tests for tango_server — brand validation (no network calls)."""

from __future__ import annotations

from sentient_ledger.config import TANGO_APPROVED_BRANDS


class TestValidateBrand:
    def test_approved_brand_returns_true(self):
        from sentient_ledger.mcp_servers.tango_server import validate_brand
        result = validate_brand("Amazon")
        assert result["approved"] is True

    def test_unapproved_brand_returns_false(self):
        from sentient_ledger.mcp_servers.tango_server import validate_brand
        result = validate_brand("RandomGiftShop")
        assert result["approved"] is False

    def test_returns_approved_brands_list(self):
        from sentient_ledger.mcp_servers.tango_server import validate_brand
        result = validate_brand("Amazon")
        assert len(result["approved_brands"]) == len(TANGO_APPROVED_BRANDS)

    def test_brand_name_in_result(self):
        from sentient_ledger.mcp_servers.tango_server import validate_brand
        result = validate_brand("Visa")
        assert result["brand_name"] == "Visa"

    def test_all_approved_brands_pass(self):
        from sentient_ledger.mcp_servers.tango_server import validate_brand
        for brand in TANGO_APPROVED_BRANDS:
            assert validate_brand(brand)["approved"] is True, f"{brand} should be approved"


class TestPlaceOrderBrandGuard:
    def test_unapproved_brand_rejected_without_api_call(self, monkeypatch):
        """place_order must reject before making any HTTP call."""
        import httpx

        called = []

        def mock_post(*args, **kwargs):
            called.append(True)
            raise AssertionError("Should not have called Tango API")

        monkeypatch.setattr(httpx, "post", mock_post)
        monkeypatch.setenv("TANGO_PLATFORM_NAME", "test")
        monkeypatch.setenv("TANGO_PLATFORM_KEY", "key")

        from sentient_ledger.mcp_servers.tango_server import place_order

        result = place_order(
            brand_name="UnauthorizedBrand",
            utid="UTID123",
            amount=50.0,
            recipient_email="test@example.com",
            recipient_name="Test User",
        )
        assert result["status"] == "rejected"
        assert "not in the approved list" in result["error"]
        assert called == []
