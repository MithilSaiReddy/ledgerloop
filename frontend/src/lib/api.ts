const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface LedgerEntry {
  id: number;
  invoice_id: number;
  type: "purchase" | "sale" | null;
  vendor: string;
  gstin: string | null;
  invoice_no: string;
  date: string;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  total: number;
  category: string;
  source?: string;
}

export interface ExceptionItem {
  id: number;
  invoice_id: number;
  filename: string;
  reason: string;
  detail: string;
  status: string;
  extracted: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: number | null;
  before: unknown;
  after: unknown;
  note: string;
  created_at: string;
}

export interface MonthBundle {
  month: string;
  entries: LedgerEntry[];
  exceptions: { id: number; filename: string; reason: string; detail: string; status: string }[];
  summary: {
    count: number;
    taxable_value: number;
    cgst: number;
    sgst: number;
    igst: number;
    grand_total: number;
    by_category: Record<string, number>;
    open_exceptions: number;
  };
}

export interface MonthSummary {
  month: string;
  count: number;
  purchases: number;
  sales: number;
  money_in: number;
  money_out: number;
  net: number;
  gst: number;
  taxable_value: number;
  total: number;
  exceptions: number;
}

export interface IngestResult {
  ok: boolean;
  status: "ledger" | "exception" | "failed";
  invoice_id: number;
  ledger_id: number | null;
  exception_id: number | null;
  reason: string | null;
  detail: string;
  vendor: string;
  total: number | null;
  month: string;
  message: string;
}

export interface UserSettings {
  owner_id: string;
  shop_name: string;
  ca_email: string;
  gstin: string | null;
  state: string | null;
  state_code: string | null;
  address: string | null;
  gst_registered: boolean;
  telegram_chat_id: string | null;
}

function authHeaders(token?: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function get<T>(path: string, token?: string | null): Promise<T> {
  const res = await fetch(`${BACKEND}${path}`, {
    cache: "no-store",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function send<T>(method: string, path: string, body?: unknown, token?: string | null): Promise<T> {
  const res = await fetch(`${BACKEND}${path}`, {
    method,
    headers: {
      ...authHeaders(token),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? `${method} ${path} failed: ${res.status}`);
  return data;
}

/** Human-readable copy for machine reason codes. */
export const REASON_LABELS: Record<string, string> = {
  DUPLICATE: "Duplicate invoice",
  INVALID_GSTIN: "GSTIN doesn't look valid",
  GSTIN_MISSING: "GSTIN missing",
  TAX_MISMATCH: "Tax amounts don't add up",
  EXTRACTION_INCOMPLETE: "Couldn't read all fields",
  BAD_DATE: "Invoice date unreadable",
  CONVERSION_FAILED: "File couldn't be read",
  LLM_UNAVAILABLE: "Processing temporarily unavailable",
  EXTRACTION_FAILED: "Couldn't extract details",
};

export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason.replaceAll("_", " ").toLowerCase();
}

export const api = {
  ledger: (month: string, token?: string | null, type?: "purchase" | "sale" | "all") =>
    get<LedgerEntry[]>(`/ledger?month=${month}${type && type !== "all" ? `&type=${type}` : ""}`, token),
  months: (token?: string | null) => get<MonthSummary[]>("/ledger/months", token),
  exceptions: (month: string, token?: string | null) =>
    get<ExceptionItem[]>(`/exceptions?month=${month}`, token),
  audit: (token?: string | null) => get<AuditEntry[]>("/audit", token),
  preview: (month: string, token?: string | null) =>
    get<{ bundle: MonthBundle; html: string }>(`/month-end/preview?month=${month}`, token),
};

export function exportUrl(month: string, format: "csv" | "json"): string {
  return `${BACKEND}/export?month=${month}&format=${format}`;
}

/** Explicit ?month= wins; otherwise current month if it has data (or nothing
 * does), else the most recent month that actually has data. */
export async function defaultMonth(
  explicit?: string | string[],
  token?: string | null,
): Promise<string> {
  if (typeof explicit === "string" && /^\d{4}-\d{2}$/.test(explicit)) return explicit;
  const cur = currentMonth();
  try {
    const summaries = await api.months(token);
    const months = summaries.map((s) => s.month);
    return months.includes(cur) || months.length === 0 ? cur : months[0];
  } catch {
    return cur;
  }
}

export async function patchLedger(id: number, field: string, value: string, token?: string | null) {
  return send<{ ok: boolean; entry: LedgerEntry }>("PATCH", `/ledger/${id}`, { field, value }, token);
}

export async function resolveException(
  id: number,
  action: "resolved" | "dismissed",
  edits?: Record<string, string>,
  token?: string | null,
) {
  return send<{ ok: boolean; ledger_id: number | null }>(
    "POST",
    `/exceptions/${id}/resolve`,
    { action, edits },
    token,
  );
}

export async function sendMonthEnd(month: string, token?: string | null) {
  return send<{ dry_run: boolean; note: string; bundle: MonthBundle }>(
    "POST",
    `/month-end/send?month=${month}`,
    undefined,
    token,
  );
}

export async function uploadInvoice(file: File, token?: string | null): Promise<IngestResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BACKEND}/invoices/upload`, {
    method: "POST",
    headers: authHeaders(token),
    body: form,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail ?? `Upload failed: ${res.status}`);
  return data as IngestResult;
}

/** Returns the user's settings, or null when onboarding hasn't happened yet. */
export async function getUserSettings(token?: string | null): Promise<UserSettings | null> {
  const res = await fetch(`${BACKEND}/user-settings/me`, { headers: authHeaders(token) });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load settings: ${res.status}`);
  return res.json();
}

export async function saveUserSettings(
  data: {
    shop_name: string;
    ca_email: string;
    gstin?: string;
    state?: string;
    state_code?: string;
    address?: string;
    gst_registered?: boolean;
    telegram_chat_id?: string;
  },
  token?: string | null,
): Promise<{ ok: boolean; created: boolean; settings: UserSettings }> {
  return send("POST", "/user-settings", data, token);
}

/** Store the Google OAuth tokens from the Supabase session so the backend
 * can send month-end email via the Gmail API as the shop owner. */
export async function saveGoogleTokens(
  accessToken: string,
  refreshToken: string | null,
  token?: string | null,
): Promise<{ ok: boolean; has_refresh: boolean }> {
  return send("POST", "/user-settings/google-tokens", {
    access_token: accessToken,
    refresh_token: refreshToken,
  }, token);
}

export function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

/** Indian GST 2-digit state codes for the business-profile dropdown. */
export const GST_STATES: { code: string; name: string }[] = [
  { code: "01", name: "Jammu & Kashmir" }, { code: "02", name: "Himachal Pradesh" },
  { code: "03", name: "Punjab" }, { code: "04", name: "Chandigarh" },
  { code: "05", name: "Uttarakhand" }, { code: "06", name: "Haryana" },
  { code: "07", name: "Delhi" }, { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" }, { code: "10", name: "Bihar" },
  { code: "11", name: "Sikkim" }, { code: "12", name: "Arunachal Pradesh" },
  { code: "13", name: "Nagaland" }, { code: "14", name: "Manipur" },
  { code: "15", name: "Mizoram" }, { code: "16", name: "Tripura" },
  { code: "17", name: "Meghalaya" }, { code: "18", name: "Assam" },
  { code: "19", name: "West Bengal" }, { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" }, { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" }, { code: "24", name: "Gujarat" },
  { code: "26", name: "Dadra & Nagar Haveli and Daman & Diu" },
  { code: "27", name: "Maharashtra" }, { code: "29", name: "Karnataka" },
  { code: "30", name: "Goa" }, { code: "31", name: "Lakshadweep" },
  { code: "32", name: "Kerala" }, { code: "33", name: "Tamil Nadu" },
  { code: "34", name: "Puducherry" }, { code: "35", name: "Andaman & Nicobar" },
  { code: "36", name: "Telangana" }, { code: "37", name: "Andhra Pradesh" },
  { code: "38", name: "Ladakh" },
];
