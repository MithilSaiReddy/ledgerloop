import Link from "next/link";
import { redirect } from "next/navigation";
import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { ExportButtons } from "@/components/send-panel";
import { LedgerTable } from "@/components/ledger-table";
import { LedgerTypeTabs } from "@/components/ledger-type-tabs";
import { MonthNav } from "@/components/month-nav";
import { api, BACKEND_URL, defaultMonth } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase-server";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

function fmt(n: number) {
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default async function LedgerPage({
  searchParams,
}: PageProps<"/ledger">) {
  const token = await getAccessToken();
  if (!token) redirect("/");

  const params = await searchParams;
  const month = await defaultMonth(params.month, token);
  const rawType = typeof params.type === "string" ? params.type : "all";
  const type = (["all", "purchase", "sale"] as const).includes(rawType as never)
    ? (rawType as "all" | "purchase" | "sale")
    : "all";

  let entries: Awaited<ReturnType<typeof api.ledger>> = [];
  let error: string | null = null;
  let months: string[] = [];
  try {
    [entries, months] = await Promise.all([
      api.ledger(month, token, type),
      api.months(token).then((ms) => ms.map((m) => m.month)).catch(() => []),
    ]);
  } catch (e) {
    entries = [];
    error = e instanceof Error ? e.message : "backend unreachable";
  }
  // always offer the current month, even with no data yet
  const cur = new Date().toISOString().slice(0, 7);
  const monthOptions = [...new Set([cur, ...months])].sort().reverse();

  const moneyIn = entries.filter((e) => e.type === "sale").reduce((s, e) => s + e.total, 0);
  const moneyOut = entries.filter((e) => e.type === "purchase").reduce((s, e) => s + e.total, 0);
  const net = moneyIn - moneyOut;

  const counts = {
    all: entries.length,
    purchase: entries.filter((e) => e.type === "purchase").length,
    sale: entries.filter((e) => e.type === "sale").length,
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ledger — {month}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Click any cell to edit it inline — every change is logged in your audit trail.
          </p>
        </div>
        <MonthNav path="/ledger" months={monthOptions} value={month} extra={{ type }} />
      </div>

      {/* Running totals */}
      <div className="grid gap-3 sm:grid-cols-3">
        <TotalsCard label="Money in" value={fmt(moneyIn)} tone="success" />
        <TotalsCard label="Money out" value={fmt(moneyOut)} />
        <TotalsCard label="Net (in − out)" value={fmt(Math.abs(net))} prefix={net >= 0 ? "+" : "−"} tone={net >= 0 ? "success" : "warning"} />
      </div>

      {/* Type filter tabs + export */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <LedgerTypeTabs month={month} value={type} counts={counts} />
        <ExportButtons month={month} />
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertTitle>Backend error</AlertTitle>
          <AlertDescription>
            {error} — is the FastAPI service running on {BACKEND_URL}?
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <LedgerTable key={`${month}:${type}`} entries={entries} />
          <p className="text-sm text-muted-foreground">
            Flagged invoices live in{" "}
            <Link href={`/exceptions?month=${month}`} className="font-medium text-primary hover:underline">
              Exceptions
            </Link>
            .
          </p>
        </>
      )}
    </div>
  );
}

function TotalsCard({
  label,
  value,
  prefix = "₹",
  tone,
}: {
  label: string;
  value: string;
  prefix?: string;
  tone?: "success" | "warning";
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p
          className={cn(
            "mt-1 tabular-nums text-xl font-semibold tracking-tight",
            tone === "success" && "text-success",
            tone === "warning" && "text-warning",
          )}
        >
          {prefix}
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
