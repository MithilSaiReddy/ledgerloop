"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EmptyState } from "@/components/empty-state";
import { useAuth } from "@/components/auth-provider";
import { reasonLabel, resolveException, type ExceptionItem } from "@/lib/api";
import { cn } from "@/lib/utils";

const REASON_VARIANT: Record<string, "warning" | "info" | "neutral" | "destructive"> = {
  DUPLICATE: "warning",
  INVALID_GSTIN: "destructive",
  GSTIN_MISSING: "destructive",
  TAX_MISMATCH: "warning",
  EXTRACTION_INCOMPLETE: "info",
  BAD_DATE: "warning",
  CONVERSION_FAILED: "neutral",
  LLM_UNAVAILABLE: "neutral",
  EXTRACTION_FAILED: "neutral",
};

const EDITABLE_FIELDS = ["vendor", "gstin", "invoice_no", "date", "taxable_value",
  "cgst", "sgst", "igst", "total", "category"] as const;

export function ExceptionsList({ items }: { items: ExceptionItem[] }) {
  const router = useRouter();
  const { session } = useAuth();
  const [resolving, setResolving] = useState<ExceptionItem | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (items.length === 0) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="All clear this month."
        description="Nothing needs your review — the agent filed everything it received."
      />
    );
  }

  function openResolve(item: ExceptionItem) {
    setResolving(item);
    setEdits({});
    setError(null);
  }

  async function act(action: "resolved" | "dismissed", item?: ExceptionItem) {
    const target = item ?? resolving;
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await resolveException(target.id, action, action === "resolved" ? edits : undefined, session?.access_token);
      toast.success(action === "resolved" ? "Pushed to your ledger" : "Dismissed — we won't ask about this again");
      setResolving(null);
      router.refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Couldn't complete that. Please try again.";
      setError(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ul className="space-y-3">
        {items.map((item) => (
          <li key={item.id}>
            <Card className="transition hover:shadow-sm">
              <CardContent className="p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={REASON_VARIANT[item.reason] ?? "neutral"}>
                        {reasonLabel(item.reason)}
                      </Badge>
                      {item.status !== "open" && (
                        <Badge variant={item.status === "resolved" ? "success" : "secondary"}>
                          {item.status}
                        </Badge>
                      )}
                      <span className="font-mono text-xs text-muted-foreground">{item.filename}</span>
                    </div>
                    <p className="text-sm text-foreground">{item.detail || reasonLabel(item.reason)}</p>
                    {item.extracted && (
                      <p className="truncate font-mono text-xs text-muted-foreground">
                        {JSON.stringify(item.extracted)}
                      </p>
                    )}
                  </div>
                  {item.status === "open" && (
                    <div className="flex shrink-0 gap-2">
                      <Button size="sm" onClick={() => openResolve(item)}>
                        Review &amp; fix
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => act("dismissed", item)} disabled={busy}>
                        Dismiss
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>

      <Dialog open={resolving !== null} onOpenChange={(open) => !open && setResolving(null)}>
        <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Fix exception — {resolving ? reasonLabel(resolving.reason) : ""}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{resolving?.detail}</p>
          <div className="space-y-2 py-2">
            <Label>Correct any misread fields before pushing to ledger</Label>
            {EDITABLE_FIELDS.map((f) => (
              <div key={f} className="grid grid-cols-[140px_1fr] items-center gap-2">
                <span className={cn("text-xs font-medium", "text-muted-foreground")}>{f}</span>
                <Input
                  placeholder={String(resolving?.extracted?.[f] ?? "")}
                  value={edits[f] ?? ""}
                  onChange={(ev) =>
                    setEdits((prev) =>
                      ev.target.value === ""
                        ? Object.fromEntries(Object.entries(prev).filter(([k]) => k !== f))
                        : { ...prev, [f]: ev.target.value }
                    )
                  }
                />
              </div>
            ))}
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setResolving(null)}>
              Cancel
            </Button>
            <Button onClick={() => act("resolved")} disabled={busy}>
              {busy ? "Pushing…" : "Push corrected row to ledger"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
