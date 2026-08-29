import { redirect } from "next/navigation";
import { AlertCircle, ScrollText } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { api } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";

const ACTION_VARIANT: Record<string, "info" | "warning" | "success" | "neutral"> = {
  ingest: "info",
  edit_ledger: "warning",
  resolve_exception: "success",
  month_end_send: "neutral",
};

const ACTION_LABEL: Record<string, string> = {
  ingest: "ingest",
  edit_ledger: "ledger edit",
  resolve_exception: "exception resolved",
  month_end_send: "month-end send",
};

export default async function AuditPage() {
  const token = await getAccessToken();
  if (!token) redirect("/");

  let rows: Awaited<ReturnType<typeof api.audit>> = [];
  let error: string | null = null;
  try {
    rows = await api.audit(token);
  } catch (e) {
    rows = [];
    error = e instanceof Error ? e.message : "backend unreachable";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every automated action, human edit and CA send — append-only.
        </p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertTitle>Backend error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!error &&
        (rows.length === 0 ? (
          <EmptyState icon={ScrollText} title="Nothing logged yet." />
        ) : (
          <ol className="relative space-y-4 border-l pl-6">
            {rows.map((r) => (
              <li key={r.id} className="relative">
                <span className="absolute -left-[31px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-background bg-muted-foreground" />
                <Card>
                  <CardContent className="p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={ACTION_VARIANT[r.action] ?? "neutral"}>
                        {ACTION_LABEL[r.action] ?? r.action}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{r.actor}</span>
                      <span className="ml-auto font-mono text-xs text-muted-foreground">
                        {r.created_at.replace("T", " ").slice(0, 19)} UTC
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-foreground">{r.note}</p>
                    {(r.before != null || r.after != null) && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-muted-foreground">
                          before / after
                        </summary>
                        <pre className="mt-1 overflow-x-auto rounded-md bg-muted p-2 font-mono text-xs">
                          {JSON.stringify({ before: r.before, after: r.after }, null, 2)}
                        </pre>
                      </details>
                    )}
                  </CardContent>
                </Card>
              </li>
            ))}
          </ol>
        ))}
    </div>
  );
}
