"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, BookOpenCheck, FileUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AddInvoiceButton } from "@/components/add-invoice-button";
import { EmptyState } from "@/components/empty-state";
import { api, type MonthSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function monthLabel(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return `${MONTH_NAMES[mo - 1]} ${y}`;
}

function inr(n: number) {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

export function DashboardView({ token }: { token: string }) {
  const [months, setMonths] = useState<MonthSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.months(token)
      .then((m) => !cancelled && setMonths(m))
      .catch(() => !cancelled && setError("Couldn't reach your books — is the backend running?"))
    return () => {
      cancelled = true;
    };
  }, [token]);

  const loading = months === null;

  const totals = (months ?? []).reduce(
    (acc, m) => ({
      moneyIn: acc.moneyIn + m.money_in,
      moneyOut: acc.moneyOut + m.money_out,
      gst: acc.gst + m.gst,
      bills: acc.bills + m.count,
      exceptions: acc.exceptions + m.exceptions,
    }),
    { moneyIn: 0, moneyOut: 0, gst: 0, bills: 0, exceptions: 0 },
  );
  const net = totals.moneyIn - totals.moneyOut;

  const monthsNeedingReview = (months ?? []).filter((m) => m.exceptions > 0);
  const pendingCount = monthsNeedingReview.reduce((n, m) => n + m.exceptions, 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Your books at a glance — bills filed, cash flow, and anything needing review.
          </p>
        </div>
        <AddInvoiceButton />
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Stat cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Bills filed" value={String(totals.bills)} sub={`${months?.length ?? 0} months`} />
        <StatCard
          label="Money in"
          value={`₹${inr(totals.moneyIn)}`}
          tone="success"
          sub="sales received"
        />
        <StatCard label="Money out" value={`₹${inr(totals.moneyOut)}`} sub="purchases" />
        <StatCard
          label="Net"
          value={`${net >= 0 ? "+" : "−"}₹${inr(Math.abs(net))}`}
          tone={net >= 0 ? "success" : "warning"}
          sub={`GST ₹${inr(totals.gst)}`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Month grid */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="flex items-center gap-2">
              <BookOpenCheck className="size-4 text-muted-foreground" />
              Months
            </CardTitle>
            <Link href="/ledger" className="text-sm font-medium text-primary hover:underline">
              Open ledger <ArrowRight className="inline size-3.5" />
            </Link>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-28 rounded-lg" />
                ))}
              </div>
            ) : (months ?? []).length === 0 ? (
              <EmptyState
                icon={FileUp}
                title="No books yet — let's start yours."
                description="Send a photo of any bill to your Telegram bot, or upload it here. We'll file it under the right month automatically."
                action={
                  <Link href="/upload">
                    <Button variant="outline">
                      <FileUp data-icon="inline-start" />
                      Upload an invoice
                    </Button>
                  </Link>
                }
              />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {(months ?? []).map((m) => (
                  <Link
                    key={m.month}
                    href={`/ledger?month=${m.month}`}
                    className="group rounded-lg border p-4 transition hover:border-ring/60 hover:shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{monthLabel(m.month)}</span>
                      {m.exceptions > 0 ? (
                        <Badge variant="warning">{m.exceptions} open</Badge>
                      ) : (
                        <Badge variant="success">All clear</Badge>
                      )}
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <p className="text-xs text-muted-foreground">In</p>
                        <p className="tabular-nums font-medium">₹{inr(m.money_in)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">Out</p>
                        <p className="tabular-nums font-medium">₹{inr(m.money_out)}</p>
                      </div>
                    </div>
                    <div className="mt-3 flex items-center justify-between border-t pt-2">
                      <span className="text-xs text-muted-foreground">
                        {m.count} bills · GST ₹{inr(m.gst)}
                      </span>
                      <span
                        className={cn(
                          "tabular-nums text-sm font-semibold",
                          m.net >= 0 ? "text-success" : "text-warning",
                        )}
                      >
                        {m.net >= 0 ? "+" : "−"}₹{inr(Math.abs(m.net))}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Needs review */}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="size-4 text-muted-foreground" />
              Needs review
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : monthsNeedingReview.length === 0 ? (
              <EmptyState
                title="All clear"
                description="Nothing needs your review right now."
              />
            ) : (
              <>
                <p className="mb-3 text-xs text-muted-foreground">
                  {pendingCount} flagged {pendingCount === 1 ? "invoice" : "invoices"} across{" "}
                  {monthsNeedingReview.length} {monthsNeedingReview.length === 1 ? "month" : "months"}.
                </p>
                <ul className="space-y-3">
                  {monthsNeedingReview.slice(0, 5).map((m) => (
                    <li key={m.month}>
                      <Link
                        href={`/exceptions?month=${m.month}`}
                        className="flex items-center justify-between rounded-lg border p-3 transition hover:border-ring/60"
                      >
                        <span className="font-medium">{monthLabel(m.month)}</span>
                        <Badge variant="warning">{m.exceptions} open</Badge>
                      </Link>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/exceptions"
                  className="mt-4 inline-flex items-center text-sm font-medium text-primary hover:underline"
                >
                  Review all <ArrowRight className="ml-1 size-3.5" />
                </Link>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
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
          {value}
        </p>
        {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
}
