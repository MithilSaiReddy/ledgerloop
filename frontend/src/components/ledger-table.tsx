"use client";

import { Fragment, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Eye, FileSearch, Loader2 } from "lucide-react";
import { toast } from "sonner";

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
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/empty-state";
import { useAuth } from "@/components/auth-provider";
import { getInvoice, getInvoiceFile, patchLedger, type LedgerEntry } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Column {
  key: string;
  label: string;
  align: "left" | "right";
  numeric?: boolean;
  /** Extra width/truncation classes so the wide grid fits without overflow. */
  wrap?: string;
  /** Hidden below a breakpoint — mobile shows only the columns that matter. */
  hide?: string;
}

const COLUMNS: Column[] = [
  { key: "date", label: "Date", align: "left" },
  { key: "vendor", label: "Vendor", align: "left", wrap: "max-w-[160px] truncate" },
  { key: "invoice_no", label: "Invoice #", align: "left" },
  { key: "gstin", label: "GSTIN", align: "left", hide: "hidden lg:table-cell" },
  { key: "category", label: "Category", align: "left", wrap: "max-w-[110px] truncate", hide: "hidden md:table-cell" },
  { key: "taxable_value", label: "Taxable ₹", align: "right", numeric: true },
  { key: "cgst", label: "CGST", align: "right", numeric: true, hide: "hidden sm:table-cell" },
  { key: "sgst", label: "SGST", align: "right", numeric: true, hide: "hidden sm:table-cell" },
  { key: "igst", label: "IGST", align: "right", numeric: true, hide: "hidden sm:table-cell" },
  { key: "total", label: "Total ₹", align: "right", numeric: true },
];

const NUMERIC_KEYS = new Set(COLUMNS.filter((c) => c.numeric).map((c) => c.key));

function fmt(n: number) {
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function SourceBadge({ source }: { source: string }) {
  const isTelegram = source === "telegram";
  return (
    <Badge variant={isTelegram ? "info" : "neutral"} title={isTelegram ? "Received via Telegram" : "Uploaded on web"}>
      {isTelegram ? "Telegram" : "Upload"}
    </Badge>
  );
}

function TypeBadge({ type }: { type: string | null }) {
  if (type !== "purchase" && type !== "sale") {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  return (
    <Badge
      variant={type === "sale" ? "success" : "warning"}
      title={type === "sale" ? "You sold this (money in)" : "You bought this (money out)"}
    >
      {type === "sale" ? "Sale" : "Purchase"}
    </Badge>
  );
}

function fmtNum(n: number | null | undefined) {
  if (n == null) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function ItemsTable({ entry }: { entry: LedgerEntry }) {
  const items = entry.items ?? [];
  if (items.length === 0) return null;
  return (
    <div className="mt-2 overflow-x-auto rounded-lg border p-2">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-8 text-xs">Product</TableHead>
            <TableHead className="h-8 text-xs">HSN</TableHead>
            <TableHead className="h-8 text-right text-xs">Qty</TableHead>
            <TableHead className="h-8 text-right text-xs">Rate</TableHead>
            <TableHead className="h-8 text-right text-xs">Amount</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((it, i) => (
            <TableRow key={i}>
              <TableCell className="max-w-[260px] py-1.5 font-medium">{it.description}</TableCell>
              <TableCell className="py-1.5 font-mono text-xs text-muted-foreground">
                {it.hsn_code ?? entry.hsn_code ?? "—"}
              </TableCell>
              <TableCell className="py-1.5 text-right tabular-nums">{fmtNum(it.quantity)}</TableCell>
              <TableCell className="py-1.5 text-right tabular-nums">{fmtNum(it.rate)}</TableCell>
              <TableCell className="py-1.5 text-right font-semibold tabular-nums">{fmtNum(it.amount)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function BillDialog({ entry, onOpenChange }: { entry: LedgerEntry; onOpenChange: (open: boolean) => void }) {
  const { session } = useAuth();
  const [file, setFile] = useState<{ url: string; kind: "image" | "pdf" | "text" | "other" } | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load the actual uploaded document once the dialog opens.
  useEffect(() => {
    let cancelled = false;
    getInvoiceFile(entry.invoice_id, session?.access_token)
      .then((r) => {
        if (!cancelled) setFile(r);
      })
      .catch(() => {
        /* leave file null — text fallback still works */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.invoice_id]);

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto max-w-5xl">
        <DialogHeader>
          <DialogTitle>
            Original invoice — {entry.vendor}
          </DialogTitle>
          <DialogDescription>
            {entry.invoice_no} · {entry.date} · filed to ledger
          </DialogDescription>
        </DialogHeader>

        {file === null && text === null && error === null && (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Loading the bill…
          </div>
        )}

        {file?.kind === "image" && (
          <div className="my-2 overflow-hidden rounded-lg border bg-muted/20">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={file.url} alt="Original invoice" className="block h-auto w-full" />
          </div>
        )}
        {file?.kind === "pdf" && (
          <div className="my-2 overflow-hidden rounded-lg border">
            <iframe src={file.url} title="Original invoice" className="h-[480px] w-full bg-white" />
          </div>
        )}

        {error && <p className="py-4 text-sm text-destructive">{error}</p>}
        {text !== null && (
          <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
            {text}
          </pre>
        )}

        <ItemsTable entry={entry} />
        {!((entry.items ?? []).length > 0) && !(file || text) && (
          <p className="py-2 text-xs text-muted-foreground">
            No line items were extracted from this bill.
          </p>
        )}

        <Button
          variant="outline"
          className="mx-auto"
          onClick={async () => {
            if (text) {
              setText(null);
              setError(null);
              return;
            }
            if (error) setError(null);
            try {
              const inv = await getInvoice(entry.invoice_id, session?.access_token);
              setText(inv.raw_text || "(no extracted bill text for this invoice)");
            } catch (e) {
              setError(e instanceof Error ? e.message : "Couldn't load the bill.");
            }
          }}
        >
          <Eye className="size-4" /> {text ? "Hide" : "Show bill text"}
        </Button>
      </DialogContent>
    </Dialog>
  );
}

function displayValue(entry: LedgerEntry, col: Column): string {
  const raw = entry[col.key as keyof LedgerEntry];
  if (raw == null || raw === "") return "—";
  if (col.numeric) {
    const n = Number(raw);
    return Number.isFinite(n) ? fmt(n) : String(raw);
  }
  return String(raw);
}

/** Validate a draft before saving. Returns an error message, or null if ok. */
function validateDraft(col: Column, draft: string): string | null {
  const value = draft.trim();
  if (col.key === "date") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Date must be YYYY-MM-DD";
    const d = new Date(`${value}T00:00:00Z`);
    if (Number.isNaN(d.getTime())) return "Date is invalid";
  } else if (NUMERIC_KEYS.has(col.key)) {
    if (value === "") return null; // blank numeric -> treated as cancel
    if (!/^-?\d*\.?\d+$/.test(value)) return "Must be a number";
  } else if (value === "") {
    // NOT NULL string columns shouldn't be blanked out
    if (col.key === "vendor" || col.key === "invoice_no") return "Can't be left blank";
  }
  return null;
}

export function LedgerTable({ entries }: { entries: LedgerEntry[] }) {
  const { session } = useAuth();
  const [rows, setRows] = useState<LedgerEntry[]>(entries);
  const [editing, setEditing] = useState<{ id: number; col: string } | null>(null);
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [billEntry, setBillEntry] = useState<LedgerEntry | null>(null);

  function toggleExpanded(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (entries.length === 0) {
    return (
      <EmptyState
        icon={FileSearch}
        title="Nothing filed yet this month."
        description="Send an invoice via Telegram or upload one — good ones land here automatically."
      />
    );
  }

  function openEdit(rowId: number, col: Column) {
    if (saving) return;
    setEditing({ id: rowId, col: col.key });
    setDraft(displayValue(rows.find((r) => r.id === rowId)!, col));
    setDraftError(null);
  }

  function cancelEdit() {
    if (saving) return;
    setEditing(null);
    setDraft("");
    setDraftError(null);
  }

  async function commit() {
    if (!editing || saving) return;
    const col = COLUMNS.find((c) => c.key === editing.col)!;
    let value = draft.trim();

    const err = validateDraft(col, value);
    if (err) {
      setDraftError(err);
      return;
    }

    const currentRow = rows.find((r) => r.id === editing.id);
    if (!currentRow) {
      setEditing(null);
      return;
    }

    const current = displayValue(currentRow, col);
    if (value === "" || value === current) {
      // Nothing meaningful to change — just close the editor.
      setEditing(null);
      return;
    }

    if (col.key === "gstin") value = value.toUpperCase();
    if (NUMERIC_KEYS.has(col.key)) value = String(Number(Number(value).toFixed(2)));

    setSaving(true);
    setDraftError(null);
    try {
      await patchLedger(editing.id, col.key, value, session?.access_token);
      // Optimistically reflect the change locally so focus/nav is preserved.
      const num = NUMERIC_KEYS.has(col.key) ? Number(value) : value;
      setRows((prev) =>
        prev.map((r) => {
          if (r.id !== editing.id) return r;
          return { ...r, [col.key]: num } as LedgerEntry;
        }),
      );
      toast.success(`Saved ${col.label} — logged in audit trail`);
      setEditing(null);
    } catch (e) {
      setDraftError(e instanceof Error ? e.message : "Couldn't save. Please try again.");
      toast.error(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  function keyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      void commit();
    } else if (e.key === "Escape") {
      cancelEdit();
    }
  }

  const currentColIndex = editing ? COLUMNS.findIndex((c) => c.key === editing.col) : -1;
  const nextCol = currentColIndex >= 0 ? COLUMNS[currentColIndex + 1] ?? null : null;

  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Type</TableHead>
                {COLUMNS.map((c) => (
                  <TableHead
                    key={c.key}
                    className={cn("whitespace-nowrap", c.align === "right" && "text-right", c.hide)}
                  >
                    {c.label}
                  </TableHead>
                ))}
                <TableHead className="hidden lg:table-cell">Source</TableHead>
                <TableHead className="w-10 hidden lg:table-cell" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((e) => {
                const isOpen = expanded.has(e.id);
                return (
                  <Fragment key={e.id}>
                    <TableRow className="hover:bg-muted/50">
                      <TableCell className="pr-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-6"
                          title={isOpen ? "Hide line items" : "Show line items"}
                          onClick={() => toggleExpanded(e.id)}
                        >
                          {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                        </Button>
                      </TableCell>
                      <TableCell className="pr-2">
                        <TypeBadge type={e.type ?? null} />
                      </TableCell>
                  {COLUMNS.map((c) => {
                    const isEditing = editing?.id === e.id && editing?.col === c.key;
                    const numeric = NUMERIC_KEYS.has(c.key);
                    const shown = displayValue(e, c);
                    return (
                      <TableCell
                        key={c.key}
                        title={isEditing ? undefined : shown === "—" ? "Click to edit" : `Click to edit — ${shown}`}
                        onClick={() => !isEditing && !saving && openEdit(e.id, c)}
                        className={cn(
                          "max-w-[220px] whitespace-nowrap",
                          c.wrap,
                          c.hide,
                          numeric && "text-right tabular-nums",
                          !isEditing && "cursor-text hover:bg-accent/40 focus-within:bg-accent/40",
                        )}
                      >
                        {isEditing ? (
                          <div className="flex items-center gap-1">
                            <Input
                              autoFocus
                              value={draft}
                              onChange={(ev) => setDraft(ev.target.value)}
                              onKeyDown={keyDown}
                              onBlur={() => {
                                if (draftError) return;
                                void commit();
                              }}
                              aria-invalid={!!draftError}
                              className={cn("h-8", numeric && "text-right tabular-nums")}
                            />
                            {saving && <Loader2 className="size-3.5 animate-spin shrink-0" />}
                          </div>
                        ) : (
                          <span
                            className={cn(
                              "block max-w-full",
                              c.key === "gstin" && "font-mono text-xs",
                              numeric && "tabular-nums",
                              c.key === "total" && "font-semibold",
                              c.wrap?.includes("truncate") && "max-w-full",
                            )}
                          >
                            {shown}
                          </span>
                        )}
                      </TableCell>
                    );
                  })}
                  <TableCell className="hidden lg:table-cell">
                    <SourceBadge source={e.source ?? "telegram"} />
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6"
                      title="View original invoice"
                      onClick={() => setBillEntry(e)}
                    >
                      <Eye className="size-4" />
                    </Button>
                  </TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow className="hover:bg-muted/30">
                        <TableCell colSpan={COLUMNS.length + 4} className="bg-muted/20 px-6 py-2">
                          {e.tax_note && (
                            <p className="mb-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
                              Tax note: {e.tax_note}
                            </p>
                          )}
                          <ItemsTable entry={e} />
                          {!((e.items ?? []).length > 0) && (
                            <p className="py-2 text-xs text-muted-foreground">
                              No line items were extracted from this bill.
                            </p>
                          )}
                          <div className="lg:hidden">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="mt-1 h-7 text-xs"
                              onClick={() => setBillEntry(e)}
                            >
                              <Eye className="mr-1 size-3.5" /> View original invoice
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>
        {draftError && editing && (
          <p className="px-4 pb-3 text-sm text-destructive">{draftError}</p>
        )}
        {editing && !draftError && (
          <p className="px-4 pb-3 text-xs text-muted-foreground">
            {saving ? "Saving…" : "↵ Save · Esc cancel"}
            {nextCol ? ` · then edit ${nextCol.label}` : ""}
          </p>
        )}
      </CardContent>
      {billEntry && <BillDialog entry={billEntry} onOpenChange={(open) => !open && setBillEntry(null)} />}
    </Card>
  );
}
