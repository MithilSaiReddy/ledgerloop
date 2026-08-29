"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { createClient } from "@/lib/supabase-browser";
import { isDemoMode } from "@/lib/demo";
import { saveGoogleTokens } from "@/lib/api";

interface AuthState {
  session: Session | null;
  loading: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  session: null,
  loading: true,
  signOut: async () => {},
});

/** A minimal stand-in Session so the whole dashboard works without Supabase. */
function demoSession(): Session {
  return {
    access_token: "demo-session",
    refresh_token: "",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    user: {
      id: "demo-user",
      aud: "authenticated",
      role: "authenticated",
      email: "demo@local",
      app_metadata: {},
      user_metadata: {},
      created_at: new Date().toISOString(),
    },
  } as Session as unknown as Session;
}

/** Persist the Google provider tokens (gmail.send scope) for month-end mail. */
async function syncGoogleTokens(session: Session) {
  const providerToken = (session as Session & { provider_token?: string }).provider_token;
  const providerRefresh = (
    session as Session & { provider_refresh_token?: string }
  ).provider_refresh_token;
  if (!providerToken) return;
  try {
    await saveGoogleTokens(providerToken, providerRefresh ?? null, session.access_token);
  } catch {
    // Non-fatal: onboarding/settings still work without Gmail tokens.
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const isDemo = isDemoMode();
  const [session, setSession] = useState<Session | null>(() =>
    isDemo ? demoSession() : null,
  );
  const [loading, setLoading] = useState(() => !isDemo);

  useEffect(() => {
    if (isDemo) {
      // Offline demo: no Supabase project to talk to.
      return;
    }
    const supabase = createClient();
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
      if (data.session) void syncGoogleTokens(data.session);
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, newSession) => {
      setSession(newSession);
      if (event === "SIGNED_IN" && newSession) void syncGoogleTokens(newSession);
    });
    return () => subscription.unsubscribe();
  }, [isDemo]);

  async function signOut() {
    if (isDemoMode()) {
      setSession(null);
      return;
    }
    await createClient().auth.signOut();
  }

  return (
    <AuthContext.Provider value={{ session, loading, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
