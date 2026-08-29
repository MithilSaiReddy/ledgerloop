import { redirect } from "next/navigation";
import { DashboardView } from "@/components/dashboard-view";
import { getAccessToken } from "@/lib/supabase-server";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const token = await getAccessToken();
  if (!token) {
    redirect("/");
  }
  return <DashboardView token={token} />;
}
