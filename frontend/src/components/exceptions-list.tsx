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
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/empty-state";
import { useAuth } from "@/components/auth-provider";
import { useIsMobile } from "@/hooks/use-mobile";
import { reasonLabel, resolveException, type ExceptionItem } from "@/lib/api";

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

type Edits = Record<string, string>;

function ResolveFields({
  item,
  edits,
  onEdit,
  error,
}: {
  item: ExceptionItem;
  edits: Edits;
  onEdit: (field: string, value: string) => void;
  error: string | null;
}) {
  return (
    <FieldGroup className="py-2">
      <p className="text-sm text-muted-foreground">{item.detail}</p>
      {EDITABLE_FIELDS.map((f) => (
        <Field key={f}>
          <FieldLabel htmlFor={`exc-${f}`}>{f}</FieldLabel>
          <Input
            id={`exc-${f}`}
            placeholder={String(item.extracted?.[f] ?? "")}
            value={edits[f] ?? ""}
            aria-invalid={!!error}
            onChange={(ev) => onEdit(f, ev.target.value)}
          />
        </Field>
      ))}
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
    </FieldGroup>
  );
}

export function ExceptionsList({ items }: { items: ExceptionItem[] }) {
  const router = useRouter();
  const isMobile = useIsMobile();
  const { session } = useAuth();
  const [resolving, setResolving] = useState<ExceptionItem | null>(null);
  const [edits, setEdits] = useState<Edits>({});
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

  const title = resolving ? `Fix exception — ${reasonLabel(resolving.reason)}` : "";

  const form = resolving && (
    <>
      <ResolveFields
        item={resolving}
        edits={edits}
        onEdit={(field, value) =>
          setEdits((prev) =>
            value === ""
              ? Object.fromEntries(Object.entries(prev).filter(([k]) => k !== field))
              : { ...prev, [field]: value }
          )
        }
        error={error}
      />
      <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
        <Button variant="outline" onClick={() => setResolving(null)}>
          Cancel
        </Button>
        <Button onClick={() => act("resolved")} disabled={busy}>
          {busy ? "Pushing…" : "Push corrected row to ledger"}
        </Button>
      </div>
    </>
  );

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
                      <p className="max-w-full truncate font-mono text-[11px] text-muted-foreground">
                        {JSON.stringify(item.extracted)}
                      </p>
                    )}
                  </div>
                  {item.status === "open" && (
                    <div className="flex shrink-0 gap-2">
                      <Button onClick={() => openResolve(item)}>
                        Review &amp; fix
                      </Button>
                      <Button variant="ghost" onClick={() => act("dismissed", item)} disabled={busy}>
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

      {isMobile ? (
        <Drawer open={resolving !== null} onOpenChange={(open) => !open && setResolving(null)}>
          <DrawerContent className="max-h-[90vh]">
            <DrawerHeader>
              <DrawerTitle>{title}</DrawerTitle>
              <DrawerDescription>Correct any misread fields before pushing to ledger.</DrawerDescription>
            </DrawerHeader>
            <div className="overflow-y-auto px-4">{form}</div>
          </DrawerContent>
        </Drawer>
      ) : (
        <Dialog open={resolving !== null} onOpenChange={(open) => !open && setResolving(null)}>
          <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>{title}</DialogTitle>
              <DialogDescription>Correct any misread fields before pushing to ledger.</DialogDescription>
            </DialogHeader>
            {form}
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
