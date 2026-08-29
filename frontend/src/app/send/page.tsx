import { redirect } from "next/navigation";
import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SendHistory, SendPanel } from "@/components/send-panel";
import { MonthNav } from "@/components/month-nav";
import { api, defaultMonth, type AuditEntry } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";

export default async function SendPage({
  searchParams,
}: PageProps<"/send">) {
  const token = await getAccessToken();
  if (!token) redirect("/");

  const params = await searchParams;
  const month = await defaultMonth(params.month, token);

  let preview: Awaited<ReturnType<typeof api.preview>> | null = null;
  let history: AuditEntry[] = [];
  let months: string[] = [];
  let error: string | null = null;
  try {
    [preview, history, months] = await Promise.all([
      api.preview(month, token),
      api.audit(token).then((a) => a.filter((x) => x.action === "month_end_send")),
      api.months(token).then((ms) => ms.map((m) => m.month)).catch(() => []),
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : "backend unreachable";
  }
  const cur = new Date().toISOString().slice(0, 7);
  const monthOptions = [...new Set([cur, ...months])].sort().reverse();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Month-end — {month}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Preview the exact email, then send to your CA on your explicit command.
            Every send is logged and reversible via dry-run mode.
          </p>
        </div>
        <MonthNav path="/send" months={monthOptions} value={month} />
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertTitle>Backend error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!error && preview && (
        <>
          <SendPanel html={preview.html} month={month} />
          <SendHistory
            sends={history.map((h) => ({
              id: h.id,
              note: h.note,
              after: h.after,
              created_at: h.created_at,
            }))}
          />
        </>
      )}
    </div>
  );
}
