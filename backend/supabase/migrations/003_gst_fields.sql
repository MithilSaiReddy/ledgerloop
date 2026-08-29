-- LedgerLoop v3: GST-aware fields (settings profile + per-invoice HSN /
-- place of supply / intra-vs-inter-state). Additive — safe to run on an
-- existing database; 001_init.sql already includes these for fresh installs.

alter table user_settings
    add column if not exists gstin text,
    add column if not exists state text,
    add column if not exists state_code text,
    add column if not exists address text,
    add column if not exists gst_registered boolean not null default false;

alter table ledger
    add column if not exists party_name text,
    add column if not exists month text not null default '',
    add column if not exists hsn_code text,
    add column if not exists place_of_supply text,
    add column if not exists is_interstate boolean,
    add column if not exists file_hash text,
    add column if not exists raw_file_ref text;

-- Backfill month from date for any rows created before this migration.
update ledger set month = left(date, 7) where month = '';

create index if not exists idx_ledger_owner_month
    on ledger (owner_id, month);
