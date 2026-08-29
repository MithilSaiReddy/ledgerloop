"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { FileSearch } from "lucide-react";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

const EDITABLE_TEXT = ["vendor", "gstin", "invoice_no", "date", "category"] as const;
const EDITABLE_NUM = ["taxable_value", "cgst", "sgst", "igst", "total"] as const;

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

export function LedgerTable({ entries }: { entries: LedgerEntry[] }) {
  const router = useRouter();
  const { session } = useAuth();
  const [editing, setEditing] = useState<LedgerEntry | null>(null);
  const [field, setField] = useState<string>("vendor");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
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

  function openEdit(entry: LedgerEntry, f: string) {
    setEditing(entry);
    setField(f);
    setValue(String(entry[f as keyof LedgerEntry] ?? ""));
    setError(null);
  }

  function changeField(next: string) {
    setField(next);
    if (editing) setValue(String(editing[next as keyof LedgerEntry] ?? ""));
  }

  async function save() {
    if (!editing) return;
    setSaving(true);
    setError(null);
    try {
      await patchLedger(editing.id, field, value, session?.access_token);
      toast.success("Saved — logged in your audit trail");
      setEditing(null);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Card className="overflow-hidden py-0">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Vendor</TableHead>
                  <TableHead>Invoice #</TableHead>
                  <TableHead>GSTIN</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead className="text-right">Taxable ₹</TableHead>
                  <TableHead className="text-right">CGST</TableHead>
                  <TableHead className="text-right">SGST</TableHead>
                  <TableHead className="text-right">IGST</TableHead>
                  <TableHead className="text-right">Total ₹</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((e) => (
                  <TableRow key={e.id} className="hover:bg-muted/50">
                    <TableCell className="whitespace-nowrap">{e.date}</TableCell>
                    <TableCell>
                      <TypeBadge type={e.type ?? null} />
                    </TableCell>
                    <TableCell className="max-w-[180px] truncate font-medium">{e.vendor}</TableCell>
                    <TableCell>{e.invoice_no}</TableCell>
                    <TableCell className="font-mono text-xs">{e.gstin ?? "—"}</TableCell>
                    <TableCell>
                      <SourceBadge source={e.source ?? "telegram"} />
                    </TableCell>
                    <TableCell>{e.category}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(e.taxable_value)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(e.cgst)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(e.sgst)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(e.igst)}</TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">{fmt(e.total)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="outline" size="sm" onClick={() => openEdit(e, "vendor")}>
                        Edit
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              Edit ledger entry — {editing?.vendor ?? ""}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="field">Field</Label>
              <Select value={field} onValueChange={changeField}>
                <SelectTrigger id="field" className="w-full">
                  <SelectValue placeholder="Select a field" />
                </SelectTrigger>
                <SelectContent>
                  {[...EDITABLE_TEXT, ...EDITABLE_NUM].map((f) => (
                    <SelectItem key={f} value={f}>
                      {f}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="value">New value</Label>
              <Input id="value" value={value} onChange={(ev) => setValue(ev.target.value)} />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={saving} size="sm">
              {saving ? "Saving…" : "Save edit"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
