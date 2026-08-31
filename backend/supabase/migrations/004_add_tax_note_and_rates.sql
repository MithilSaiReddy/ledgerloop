-- LedgerLoop v4: auto-derived GST support.
-- Additive — safe to run on an existing database.
--
-- ledger.tax_note     : why CGST/SGST/IGST were derived, if the bill printed
--                        no tax split (embedded in total, or derived by category).
-- user_settings.tax_rates : JSON map {category: gst_rate} — per-owner overrides
--                        for the auto-derive rates.

alter table ledger
    add column if not exists tax_note text;

alter table user_settings
    add column if not exists tax_rates text;