/** Whether the frontend should run in offline demo mode (no Supabase/Google). */
export function isDemoMode(): boolean {
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_DEMO_MODE === "1") {
    return true;
  }
  // Auto-detect: no real Supabase keys configured.
  return !process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
}
