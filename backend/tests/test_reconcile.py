from app.pipeline.reconcile import (
    _shop_rate,
    apply_tax_fallback,
    check_tax_sum,
    normalize_vendor,
    parse_date,
    reconcile,
)

BASE = {
    "vendor": "Sharma Kirana Stores",
    "gstin": "27SHKPS1234A1Z5",
    "invoice_no": "SK/2025/0100",
    "date": "2025-06-13",
    "taxable_value": 10000.00,
    "cgst": 900.00,
    "sgst": 900.00,
    "igst": 0.0,
    "total": 11800.00,
    "category": "groceries",
    "hsn_code": "5210",
    "place_of_supply": "27-Maharashtra",
}


def ok_extracted(**over):
    return {**BASE, **over}


class TestParseDate:
    def test_iso(self):
        assert parse_date("2025-06-13") == "2025-06-13"

    def test_dmy_slash(self):
        assert parse_date("13/06/2025") == "2025-06-13"

    def test_dmy_dash(self):
        assert parse_date("05-03-2025") == "2025-03-05"  # DD/MM assumed

    def test_dot_format(self):
        assert parse_date("13.6.2025") == "2025-06-13"
        assert parse_date("13.06.2025") == "2025-06-13"

    def test_two_digit_year_slash(self):
        assert parse_date("25/9/26") == "2026-09-25"  # DD/MM/YY, relevant year

    def test_two_digit_year_single_digits(self):
        assert parse_date("2/1/26") == "2026-01-02"

    def test_two_digit_year_dash(self):
        assert parse_date("13-06-26") == "2026-06-13"

    def test_two_digit_year_dot(self):
        assert parse_date("13.06.25") == "2025-06-13"

    def test_two_digit_year_old_bill(self):
        assert parse_date("09/09/99") == "1999-09-09"  # closest century, not 2099

    def test_garbage(self):
        assert parse_date("sometime last week") is None

    def test_none(self):
        assert parse_date(None) is None


class TestNormalizeVendor:
    def test_case_punct(self):
        assert normalize_vendor("Sharma Kirana  Stores!") == "sharmakiranastores"


class TestTaxSum:
    def test_exact(self):
        assert check_tax_sum(ok_extracted())

    def test_within_tolerance(self):
        assert check_tax_sum(ok_extracted(total=11800.99))  # 99p off

    def test_outside_tolerance(self):
        assert not check_tax_sum(ok_extracted(total=11950.00))  # ₹150 off


class TestReconcile:
    def test_clean_row(self):
        row, reason, detail = reconcile(ok_extracted(), set())
        assert reason is None
        assert row["vendor"] == "Sharma Kirana Stores"
        assert row["total"] == 11800.00
        assert row["date"] == "2025-06-13"

    def test_items_carried_through(self):
        items = [{"description": "Rice 5kg", "hsn_code": "1006",
                  "quantity": 2.0, "rate": 50.0, "amount": 100.0}]
        row, reason, _ = reconcile(ok_extracted(items=items), set())
        assert reason is None
        assert row["items"] == items

    def test_items_default_empty(self):
        row, reason, _ = reconcile(ok_extracted(), set())
        assert reason is None
        assert row["items"] == []

    def test_duplicate(self):
        pair = {("sharmakiranastores", "SK/2025/0100")}
        row, reason, detail = reconcile(ok_extracted(), pair)
        assert row is None and reason == "DUPLICATE"

    def test_invalid_gstin(self):
        # corrupts the checksum character of a valid-format GSTIN
        row, reason, _ = reconcile(ok_extracted(gstin="27SHKPS1234A1Z4"), set())
        assert reason == "INVALID_GSTIN"

    def test_missing_gstin(self):
        row, reason, _ = reconcile(ok_extracted(gstin=None), set())
        assert reason == "GSTIN_MISSING"

    def test_tax_mismatch(self):
        row, reason, _ = reconcile(ok_extracted(total=12000.0), set())
        assert reason == "TAX_MISMATCH"

    def test_missing_required(self):
        row, reason, _ = reconcile(ok_extracted(invoice_no=None), set())
        assert reason == "EXTRACTION_INCOMPLETE"

    def test_bad_date(self):
        row, reason, _ = reconcile(ok_extracted(date="last Tuesday"), set())
        assert reason == "BAD_DATE"

    def test_igst_variant(self):
        from app.gstin import gstin_checksum_char

        valid_29 = "29SHKPS1234A1Z" + gstin_checksum_char("29SHKPS1234A1Z")
        row, reason, _ = reconcile(
            ok_extracted(cgst=0, sgst=0, igst=1800.0, gstin=valid_29), set()
        )
        assert reason is None and row["igst"] == 1800.0

    def test_number_coercion(self):
        extracted = ok_extracted(taxable_value="₹10,000", total="11800")
        row, reason, _ = reconcile(extracted, set())
        assert reason is None and row["taxable_value"] == 10000.0

    def test_hsn_missing(self):
        row, reason, _ = reconcile(ok_extracted(hsn_code=None), set())
        assert reason == "HSN_MISSING"

    def test_hsn_invalid(self):
        row, reason, _ = reconcile(ok_extracted(hsn_code="12AB"), set())
        assert reason == "HSN_MISSING"

    def test_hsn_valid_lengths(self):
        for code in ("5210", "851712", "34022010"):
            row, reason, _ = reconcile(ok_extracted(hsn_code=code), set())
            assert reason is None, code

    def test_derives_month_and_is_interstate(self):
        taxable = 10000.0
        igst = 1800.0
        row, reason, _ = reconcile(
            ok_extracted(cgst=0, sgst=0, igst=igst,
                         taxable_value=taxable, total=round(taxable + igst, 2),
                         place_of_supply="29-Karnataka"),
            set(),
            owner={"state_code": "27", "gst_registered": True},
        )
        assert reason is None
        assert row["month"] == "2025-06"
        assert row["is_interstate"] is True

    def test_intrastate_with_igst_flags(self):
        row, reason, _ = reconcile(
            ok_extracted(cgst=0, sgst=0, igst=1800.0),
            set(),
            owner={"state_code": "27", "gst_registered": True},
        )
        assert reason == "TAX_TREATMENT_MISMATCH"

    def test_interstate_with_cgst_flags(self):
        from app.gstin import gstin_checksum_char

        valid_29 = "29SHKPS1234A1Z" + gstin_checksum_char("29SHKPS1234A1Z")
        row, reason, _ = reconcile(
            ok_extracted(gstin=valid_29, cgst=900.0, sgst=900.0, igst=0.0,
                         place_of_supply="29-Karnataka"),
            set(),
            owner={"state_code": "27", "gst_registered": True},
        )
        assert reason == "TAX_TREATMENT_MISMATCH"

    def test_intrastate_unequal_cgst_sgst_flags(self):
        row, reason, _ = reconcile(
            ok_extracted(cgst=900.0, sgst=100.0, total=11000.0),
            set(),
            owner={"state_code": "27", "gst_registered": True},
        )
        assert reason == "TAX_TREATMENT_MISMATCH"

    def test_interstate_igst_ok(self):
        from app.gstin import gstin_checksum_char

        valid_29 = "29SHKPS1234A1Z" + gstin_checksum_char("29SHKPS1234A1Z")
        taxable = 10000.0
        igst = 1800.0
        row, reason, _ = reconcile(
            ok_extracted(gstin=valid_29, cgst=0, sgst=0, igst=igst,
                         taxable_value=taxable, total=round(taxable + igst, 2),
                         place_of_supply="29-Karnataka"),
            set(),
            owner={"state_code": "27", "gst_registered": True},
        )
        assert reason is None
        assert row["is_interstate"] is True and row["igst"] == igst


class TestApplyTaxFallback:
    def test_existing_tax_untouched(self):
        out, note = apply_tax_fallback(
            ok_extracted(cgst=900.0, sgst=900.0), {"state_code": "27"}
        )
        assert note is None
        assert out["cgst"] == 900.0 and out["sgst"] == 900.0

    def test_embedded_tax_intra_split(self):
        out, note = apply_tax_fallback(
            ok_extracted(cgst=0, sgst=0, igst=0, taxable_value=10000, total=11800),
            {"state_code": "27", "gst_registered": True},
        )
        assert note and "embedded" in note
        assert out["cgst"] == 900.0 and out["sgst"] == 900.0 and out["igst"] == 0.0

    def test_embedded_tax_inter_igst(self):
        out, note = apply_tax_fallback(
            ok_extracted(cgst=0, sgst=0, igst=0, taxable_value=10000, total=11800,
                         place_of_supply="29-Karnataka"),
            {"state_code": "27", "gst_registered": True},
        )
        assert note and "IGST" in note
        assert out["igst"] == 1800.0 and out["cgst"] == 0.0 and out["sgst"] == 0.0

    def test_sale_inclusive_derive_by_category(self):
        # No tax printed; no shop default set, so the apparel category's 5% (GST
        # 2.0 merit rate) applies on an inclusive lump total.
        out, note = apply_tax_fallback(
            ok_extracted(type="sale", category="apparel", cgst=0, sgst=0, igst=0,
                         taxable_value=10500, total=10500, place_of_supply="27-Maharashtra"),
            {"state_code": "27", "gst_registered": True},
        )
        assert note and "5%" in note and "derived" in note
        assert out["taxable_value"] == 10000.0
        assert out["cgst"] == 250.0 and out["sgst"] == 250.0 and out["igst"] == 0.0

    def test_sale_owner_default_rate_wins(self):
        out, note = apply_tax_fallback(
            ok_extracted(type="sale", category="apparel", cgst=0, sgst=0, igst=0,
                         taxable_value=10500, total=10500, place_of_supply="27-Maharashtra"),
            {"state_code": "27", "gst_registered": True, "tax_rates": {"default": 5.0}},
        )
        assert note and "5%" in note and "your default" in note
        assert out["taxable_value"] == 10000.0
        assert out["cgst"] == 250.0 and out["sgst"] == 250.0

    def test_purchase_no_tax_flags_only(self):
        out, note = apply_tax_fallback(
            ok_extracted(type="purchase", category="groceries", cgst=0, sgst=0, igst=0,
                         taxable_value=10000, total=10000),
            {"state_code": "27", "gst_registered": True},
        )
        assert note and "purchase" in note and "verify" in note
        assert out["cgst"] == 0.0 and out["sgst"] == 0.0 and out["igst"] == 0.0

    def test_no_derive_when_not_registered(self):
        out, note = apply_tax_fallback(
            ok_extracted(type="sale", category="apparel", cgst=0, sgst=0, igst=0,
                         taxable_value=11200, total=11200),
            {"state_code": "27", "gst_registered": False},
        )
        assert note is None and out["taxable_value"] == 11200.0

    def test_unknown_category_uses_standard_rate(self):
        # No shop default and an unmapped category -> 18% standard rate.
        out, note = apply_tax_fallback(
            ok_extracted(type="sale", category="miscellaneous", cgst=0, sgst=0, igst=0,
                         taxable_value=1180, total=1180, place_of_supply="27-Maharashtra"),
            {"state_code": "27", "gst_registered": True},
        )
        assert note and "18%" in note and "standard rate" in note
        assert out["taxable_value"] == 1000.0
        assert out["cgst"] == 90.0 and out["sgst"] == 90.0

    def test_rows_too_messy_to_derive(self):
        # Unparseable numbers = nothing to work from.
        out, note = apply_tax_fallback(
            ok_extracted(type="sale", category="apparel", cgst=0, sgst=0, igst=0,
                         taxable_value=None, total=None),
            {"state_code": "27", "gst_registered": True},
        )
        assert note is None and out["taxable_value"] is None


class TestShopRate:
    def test_owner_default_wins(self):
        assert _shop_rate(
            {"tax_rates": {"default": 5.0}}, "apparel"
        ) == (5.0, "your default rate")

    def test_category_fallback_without_default(self):
        assert _shop_rate({}, "apparel") == (5.0, "bill category default")
        assert _shop_rate({}, "electronics") == (18.0, "bill category default")

    def test_standard_rate_last_resort(self):
        assert _shop_rate({}, "miscellaneous") == (18.0, "standard rate")
        assert _shop_rate({}, None) == (18.0, "standard rate")

    def test_zero_default_disables_derive(self):
        out, note = apply_tax_fallback(
            ok_extracted(type="sale", category="apparel", cgst=0, sgst=0, igst=0,
                         taxable_value=10500, total=10500),
            {"state_code": "27", "gst_registered": True, "tax_rates": {"default": 0.0}},
        )
        assert note is None and out["taxable_value"] == 10500.0


class TestSingleDefaultDerive:
    def test_uses_shop_default_not_item_hsn(self):
        # A bill with mixed-HSN items still uses the owner's single default.
        items = [
            {"description": "Kurti", "hsn_code": "6204", "amount": 5000.0},
            {"description": "Charger", "hsn_code": "8507", "amount": 4000.0},
        ]
        out, note = apply_tax_fallback(
            ok_extracted(type="sale", category="apparel", cgst=0, sgst=0, igst=0,
                         taxable_value=9000, total=9000, items=items,
                         place_of_supply="27-Maharashtra"),
            {"state_code": "27", "gst_registered": True, "tax_rates": {"default": 5.0}},
        )
        assert note and "5%" in note and "your default" in note
        taxable = out["taxable_value"]
        assert taxable != 9000.0
        assert out["cgst"] == out["sgst"]
        assert abs((taxable + out["cgst"] + out["sgst"]) - 9000.0) < 0.01

    def test_category_default_when_no_shop_rate(self):
        out, note = apply_tax_fallback(
            ok_extracted(type="sale", category="pharma", cgst=0, sgst=0, igst=0,
                         taxable_value=10500, total=10500,
                         items=[{"description": "Syrup", "hsn_code": "3004", "amount": 10500.0}],
                         place_of_supply="27-Maharashtra"),
            {"state_code": "27", "gst_registered": True},
        )
        assert note and "5%" in note and "bill category default" in note
        assert out["taxable_value"] == 10000.0
        assert out["cgst"] == 250.0 and out["sgst"] == 250.0


class TestReconcileTaxFallback:
    def test_clean_row_tax_note_none(self):
        row, reason, _ = reconcile(ok_extracted(), set())
        assert reason is None and row["tax_note"] is None

    def test_embedded_tax_row_reconciles(self):
        row, reason, _ = reconcile(
            ok_extracted(cgst=0, sgst=0, igst=0, taxable_value=10000, total=11800),
            set(),
            owner={"state_code": "27", "gst_registered": True},
        )
        assert reason is None
        assert row["cgst"] == 900.0 and row["sgst"] == 900.0
        assert row["tax_note"] and "embedded" in row["tax_note"]

    def test_sale_derive_row_reconciles(self):
        row, reason, _ = reconcile(
            ok_extracted(type="sale", category="apparel", cgst=0, sgst=0, igst=0,
                         taxable_value=10500, total=10500),
            set(),
            owner={"state_code": "27", "gst_registered": True},
        )
        assert reason is None
        assert row["taxable_value"] == 10000.0
        assert row["cgst"] == 250.0 and row["sgst"] == 250.0
        assert "derived" in row["tax_note"]
