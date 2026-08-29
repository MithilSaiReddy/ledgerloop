"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { getUserSettings } from "@/lib/api";

function CallbackInner() {
  const router = useRouter();
  const [done, setDone] = useState(false);
  const routed = useRef(false);

  useEffect(() => {
    if (done && !routed.current) {
      routed.current = true;
      void (async () => {
        try {
          const { createClient } = await import("@/lib/supabase-browser");
          const { data } = await createClient().auth.getSession();
          const token = data.session?.access_token;
          const settings = token ? await getUserSettings(token) : null;
          router.replace(settings ? "/dashboard" : "/onboarding");
        } catch {
          // Backend unreachable — send to onboarding which will surface the error.
          router.replace("/onboarding");
        }
      })();
    }
  }, [done, router]);

  useEffect(() => {
    // The browser supabase client exchanges the PKCE ?code= automatically.
    // Wait for the session event, then decide where to go.
    let unsub = () => {};
    const fallback = setTimeout(() => setDone(true), 8000);
    void (async () => {
      const { createClient } = await import("@/lib/supabase-browser");
      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      if (data.session) {
        clearTimeout(fallback);
        setDone(true);
      }
      const {
        data: { subscription },
      } = supabase.auth.onAuthStateChange((event) => {
        if (event === "SIGNED_IN" || event === "INITIAL_SESSION") {
          clearTimeout(fallback);
          setDone(true);
        }
      });
      unsub = () => subscription.unsubscribe();
    })();
    return () => {
      clearTimeout(fallback);
      unsub();
    };
  }, []);

  return <p className="mt-24 text-center text-muted-foreground">Signing you in…</p>;
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<p className="mt-24 text-center text-muted-foreground">Signing you in…</p>}>
      <CallbackInner />
    </Suspense>
  );
}
