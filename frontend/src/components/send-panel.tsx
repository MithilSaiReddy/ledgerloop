"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Download, FlaskConical } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/components/auth-provider";
import { exportUrl, sendMonthEnd, type MonthBundle } from "@/lib/api";

async function downloadExport(
  month: string,
  format: "csv" | "json",
  type?: "purchase" | "sales",
  token?: string | null,
) {
  const res = await fetch(exportUrl(month, format, type), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = type ? `${type}-${month}.csv` : `ledgerloop-${month}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function ExportButtons({ month }: { month: string }) {
  const { session } = useAuth();
  const [busy, setBusy] = useState(false);

  async function download(type: "purchase" | "sales" | "json") {
    setBusy(true);
    try {
      if (type === "json") {
        await downloadExport(month, "json", undefined, session?.access_token);
      } else {
        await downloadExport(month, "csv", type, session?.access_token);
      }
      toast.success(
        type === "json"
          ? "Full detail downloaded as JSON"
          : `${type[0].toUpperCase()}${type.slice(1)} register downloaded`,
      );
    } catch {
      toast.error("Couldn't export the ledger. Is the backend running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-muted-foreground">Export:</span>
      <Button variant="outline" size="sm" disabled={busy} onClick={() => download("purchase")}>
        <Download className="mr-1.5 size-3.5" />
        Purchases (CSV)
      </Button>
      <Button variant="outline" size="sm" disabled={busy} onClick={() => download("sales")}>
        <Download className="mr-1.5 size-3.5" />
        Sales (CSV)
      </Button>
      <Button variant="outline" size="sm" disabled={busy} onClick={() => download("json")}>
        <Download className="mr-1.5 size-3.5" />
        Full detail (JSON)
      </Button>
    </div>
  );
}

export function SendPanel({ html, month }: { html: string; month: string }) {
  const router = useRouter();
  const { session } = useAuth();
  const [state, setState] = useState<"idle" | "sending" | "done">("idle");
  const [result, setResult] = useState<{ dry_run: boolean; note: string; bundle: MonthBundle } | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function doSend() {
    setConfirmOpen(false);
    setState("sending");
    setError(null);
    try {
      const data = await sendMonthEnd(month, session?.access_token);
      setResult(data);
      setState("done");
      toast.success(data.dry_run ? "Preview logged (dry-run — nothing emailed)" : "Registers sent to your CA");
      router.refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Send failed. Please try again.";
      setError(msg);
      toast.error(msg);
      setState("idle");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => setConfirmOpen(true)} disabled={state === "sending"} size="lg">
          {state === "sending" ? "Sending…" : "Send to CA now"}
        </Button>
        <ExportButtons month={month} />
        {error && <span className="text-sm text-destructive">{error}</span>}
        {result && (
          <span className="flex items-center gap-1.5 text-sm">
            {result.dry_run ? (
              <FlaskConical className="size-4 text-muted-foreground" />
            ) : (
              <CheckCircle2 className="size-4 text-success" />
            )}
            {result.dry_run ? "Dry-run: rendered + logged, NOT emailed. " : "Emailed. "}
            <span className="font-mono text-xs text-muted-foreground">{result.note}</span>
          </span>
        )}
      </div>

      <Card className="gap-0 overflow-hidden py-0">
        <CardHeader className="border-b px-4 py-2.5">
          <CardTitle className="text-xs font-medium text-muted-foreground">
            Email preview — exactly what your CA will receive
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <iframe title="email preview" srcDoc={html} className="h-[600px] w-full" sandbox="" />
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm send to CA</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This emails the {month} purchase and sales registers (CSV, one row
            per bill) with a short note to the CA address on your account, and
            records it in your audit log. No filing or approval happens
            automatically.
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button onClick={doSend}>Yes, send it</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function SendHistory({
  sends,
}: {
  sends: { id: number; note: string; after: unknown; created_at: string }[];
}) {
  return (
    <div className="space-y-2">
      <h2 className="font-semibold">Send history</h2>
      {sends.length === 0 && <p className="text-sm text-muted-foreground">No month-end sends yet.</p>}
      <ul className="space-y-2">
        {sends.map((s) => {
          const info = s.after as { month?: string; invoice_count?: number; exception_count?: number; hash?: string };
          return (
            <li key={s.id}>
              <Card>
                <CardContent className="p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="neutral">{info.month ?? "?"}</Badge>
                    <span className="text-muted-foreground">
                      {info.invoice_count ?? 0} invoices · {info.exception_count ?? 0} exceptions
                    </span>
                    <Badge variant={s.note.includes("dry-run") ? "secondary" : "success"}>
                      {s.note.includes("dry-run") ? "dry-run" : "sent"}
                    </Badge>
                    <span className="ml-auto font-mono text-xs text-muted-foreground">
                      {s.created_at.replace("T", " ").slice(0, 19)} UTC
                    </span>
                  </div>
                  <Separator className="my-2" />
                  <p className="font-mono text-xs text-muted-foreground">{s.note}</p>
                </CardContent>
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
