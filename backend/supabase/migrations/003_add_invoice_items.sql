-- Per-invoice line items: product description, HSN, qty, rate, amount.
alter table ledger add column if not exists items text;