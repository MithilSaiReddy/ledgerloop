-- Add purchase/sale classification to the ledger.
alter table ledger add column if not exists type text;

create index if not exists idx_ledger_owner_month_type
    on ledger (owner_id, date, type);
