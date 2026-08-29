import { redirect } from "next/navigation";
import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ExceptionsList } from "@/components/exceptions-list";
import { MonthNav } from "@/components/month-nav";
import { api, defaultMonth } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";

export default async function ExceptionsPage({
  searchParams,
}: PageProps<"/exceptions">) {
  const token = await getAccessToken();
  if (!token) redirect("/");

  const params = await searchParams;
  const month = await defaultMonth(params.month, token);

  let items: Awaited<ReturnType<typeof api.exceptions>> = [];
  let months: string[] = [];
  let error: string | null = null;
  try {
    [items, months] = await Promise.all([
      api.exceptions(month, token),
      api.months(token).then((ms) => ms.map((m) => m.month)).catch(() => []),
    ]);
  } catch (e) {
    items = [];
    error = e instanceof Error ? e.message : "backend unreachable";
  }
  const cur = new Date().toISOString().slice(0, 7);
  const monthOptions = [...new Set([cur, ...months])].sort().reverse();

  const openCount = items.filter((i) => i.status === "open").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Exceptions — {month}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {items.length} flagged · {openCount} open. The agent flags anything it
            can&apos;t confidently reconcile; a human makes the final call.
          </p>
        </div>
        <MonthNav path="/exceptions" months={monthOptions} value={month} />
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertTitle>Backend error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!error && <ExceptionsList items={items} />}
    </div>
  );
}
