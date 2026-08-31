from app.pipeline.structure import normalize_extraction


def _raw(**over):
    base = {
        "type": "sale",
        "vendor": "Vibgyor Studio",
        "party_name": "Lumi (Gayathou)",
        "gstin": "27ABC1234567A1Z5",
        "invoice_no": "1198",
        "date": "2026-09-25",
        "taxable_value": 2525.42,
        "cgst": 35.71,
        "sgst": 35.71,
        "igst": 0.0,
        "total": 3000.0,
        "category": "apparel",
        "hsn_code": "6204",
        "place_of_supply": "27-Maharashtra",
    }
    return {**base, **over}


class TestNormalizeExtractionVendor:
    def test_sale_vendor_becomes_customer(self):
        out = normalize_extraction(_raw())
        assert out["type"] == "sale"
        assert out["vendor"] == "Lumi (Gayathou)"
        assert out["party_name"] == "Lumi (Gayathou)"

    def test_sale_vendor_ignored_when_no_party(self):
        out = normalize_extraction(_raw(party_name=None))
        assert out["vendor"] == "Vibgyor Studio"

    def test_purchase_vendor_unchanged(self):
        out = normalize_extraction(_raw(type="purchase", vendor="Sharma Suppliers",
                                        party_name=None))
        assert out["vendor"] == "Sharma Suppliers"

    def test_sale_when_vendor_equals_party_unchanged(self):
        out = normalize_extraction(_raw(party_name="Vibgyor Studio"))
        assert out["vendor"] == "Vibgyor Studio"

    def test_sale_wrong_type_string_is_null(self):
        out = normalize_extraction(_raw(type="other"))
        assert out["type"] is None
        assert out["vendor"] == "Vibgyor Studio"