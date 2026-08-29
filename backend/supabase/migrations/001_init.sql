-- LedgerLoop v2: initial schema + row level security
-- Run in Supabase dashboard: SQL Editor -> New query -> paste -> Run

create table if not exists public.invoices (
    id bigint generated always as identity primary key,
    owner_id text not null,
    filename text not null,
    source text not null default 'telegram',
    telegram_user_id text,
    raw_text text,
    converter_used text not null default 'markitdown',
    extracted_json text,
    status text not null default 'processing',
    created_at timestamptz not null default now()
);

create table if not exists public.ledger (
    id bigint generated always as identity primary key,
    owner_id text not null,
    invoice_id bigint not null references public.invoices (id) on delete cascade,
    vendor text not null,
    party_name text,
    gstin text,
    invoice_no text not null,
    date text not null,
    month text not null default '',
    type text,
    taxable_value double precision not null,
    cgst double precision not null default 0,
    sgst double precision not null default 0,
    igst double precision not null default 0,
    total double precision not null,
    category text not null default 'uncategorized',
    hsn_code text,
    place_of_supply text,
    is_interstate boolean,
    file_hash text,
    raw_file_ref text,
    edited_fields text not null default '[]',
    created_at timestamptz not null default now()
);

create table if not exists public.exceptions (
    id bigint generated always as identity primary key,
    owner_id text not null,
    invoice_id bigint not null references public.invoices (id) on delete cascade,
    reason text not null,
    detail text not null default '',
    extracted_json text,
    status text not null default 'open',
    resolved_ledger_id bigint references public.ledger (id),
    month text not null default '',
    created_at timestamptz not null default now()
);

create table if not exists public.audit_log (
    id bigint generated always as identity primary key,
    owner_id text not null,
    actor text not null,
    action text not null,
    entity_type text not null,
    entity_id bigint,
    before_json text,
    after_json text,
    note text not null default '',
    created_at timestamptz not null default now()
);

create table if not exists public.user_settings (
    owner_id text primary key,
    ca_email text not null default '',
    shop_name text not null default '',
    gstin text,
    state text,
    state_code text,
    address text,
    gst_registered boolean not null default false,
    telegram_chat_id text,
    google_access_token text,
    google_refresh_token text,
    google_token_expiry timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists idx_invoices_owner on public.invoices (owner_id);
create index if not exists idx_ledger_owner_month on public.ledger (owner_id, month);
create index if not exists idx_exceptions_owner_status on public.exceptions (owner_id, status);
create index if not exists idx_audit_owner on public.audit_log (owner_id);

-- Row level security: each user sees only their own rows.
alter table public.invoices      enable row level security;
alter table public.ledger        enable row level security;
alter table public.exceptions    enable row level security;
alter table public.audit_log     enable row level security;
alter table public.user_settings enable row level security;

create policy "own invoices"   on public.invoices      for all using (auth.uid()::text = owner_id) with check (auth.uid()::text = owner_id);
create policy "own ledger"     on public.ledger        for all using (auth.uid()::text = owner_id) with check (auth.uid()::text = owner_id);
create policy "own exceptions" on public.exceptions    for all using (auth.uid()::text = owner_id) with check (auth.uid()::text = owner_id);
create policy "own audit"      on public.audit_log     for all using (auth.uid()::text = owner_id) with check (auth.uid()::text = owner_id);
create policy "own settings"   on public.user_settings for all using (auth.uid()::text = owner_id) with check (auth.uid()::text = owner_id);
