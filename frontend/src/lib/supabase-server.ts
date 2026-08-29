import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { isDemoMode } from "@/lib/demo";

export async function createClient() {
  if (isDemoMode()) {
    // Demo mode: the backend accepts requests without a token and scopes every
    // row to the demo owner. There's no real Supabase project to talk to.
    return null;
  }
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from a Server Component — safe to ignore when the
            // browser client refreshes the session on the next request.
          }
        },
      },
    },
  );
}

/** Returns a valid access token for backend calls, or null when signed out.
 * In demo mode returns a sentinel token so existing `if (!token) redirect(...)`
 * guards stay satisfied; the backend scopes everything to the demo owner. */
export async function getAccessToken(): Promise<string | null> {
  if (isDemoMode()) return "demo-session";
  const supabase = await createClient();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
