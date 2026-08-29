"use client";

import { useState } from "react";
import { FileSearch, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
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
import { patchLedger, type LedgerEntry } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Column {
  key: string;
  label: string;
  align: "left" | "right";
  numeric?: boolean;
  /** Extra width/truncation classes so the wide grid fits without overflow. */
  wrap?: string;
}

const COLUMNS: Column[] = [
  { key: "date", label: "Date", align: "left" },
  { key: "vendor", label: "Vendor", align: "left", wrap: "max-w-[150px] truncate" },
  { key: "invoice_no", label: "Invoice #", align: "left" },
  { key: "gstin", label: "GSTIN", align: "left" },
  { key: "hsn_code", label: "HSN", align: "left" },
  { key: "place_of_supply", label: "Place of Supply", align: "left", wrap: "max-w-[130px] truncate" },
  { key: "category", label: "Category", align: "left", wrap: "max-w-[120px] truncate" },
  { key: "taxable_value", label: "Taxable ₹", align: "right", numeric: true },
  { key: "cgst", label: "CGST", align: "right", numeric: true },
  { key: "sgst", label: "SGST", align: "right", numeric: true },
  { key: "igst", label: "IGST", align: "right", numeric: true },
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
                <TableHead>Type</TableHead>
                {COLUMNS.map((c) => (
                  <TableHead key={c.key} className={cn("whitespace-nowrap", c.align === "right" && "text-right")}>
                    {c.label}
                  </TableHead>
                ))}
                <TableHead className="hidden lg:table-cell">Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((e) => (
                <TableRow key={e.id} className="hover:bg-muted/50">
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
                </TableRow>
              ))}
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
    </Card>
  );
}
