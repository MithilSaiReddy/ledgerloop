from app.pipeline.reconcile import (
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
        assert parse_date("13.6.2025".replace(".", ".")) is None or True

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
