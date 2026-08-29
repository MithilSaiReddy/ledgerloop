"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ArrowRight, BookOpenCheck, ShieldCheck, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/components/auth-provider";
import { createClient } from "@/lib/supabase-browser";
import { isDemoMode } from "@/lib/demo";

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden>
      <path fill="#EA4335" d="M12 5.04c1.62 0 3.06.56 4.2 1.64l3.12-3.12C17.46 1.8 14.96.75 12 .75 7.9.75 4.26 3.1 2.5 6.56l3.66 2.84c.87-2.6 3.25-4.36 5.84-4.36z" />
      <path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.14 2.73-2.4 3.58l3.68 2.85c2.15-1.99 3.74-4.93 3.74-8.67z" />
      <path fill="#FBBC05" d="M6.16 14.6A7.2 7.2 0 0 1 5.78 12c0-.9.16-1.78.38-2.6L2.5 6.56A11.22 11.22 0 0 0 1.25 12c0 1.95.47 3.78 1.25 5.44l3.66-2.84z" />
      <path fill="#34A853" d="M12 23.25c3.04 0 5.6-1 7.46-2.72l-3.68-2.85c-1.02.69-2.33 1.1-3.78 1.1-2.59 0-4.97-1.76-5.84-4.36l-3.66 2.84C4.26 20.9 7.9 23.25 12 23.25z" />
    </svg>
  );
}

const FEATURES = [
  {
    icon: Zap,
    title: "Auto-filed ledger",
    text: "Send any bill over Telegram or upload it — we read it, flag mistakes, and file it under the right month.",
  },
  {
    icon: ShieldCheck,
    title: "Human checks every flag",
    text: "Nothing is auto-filed or auto-approved. Anything suspicious lands in your review queue for your final call.",
  },
  {
    icon: BookOpenCheck,
    title: "Clear month-end handoff",
    text: "Preview the exact summary and email it to your CA on your explicit command — always logged in your audit trail.",
  },
];

export default function Home() {
  const router = useRouter();
  const { session, loading } = useAuth();

  useEffect(() => {
    if (!loading && session) {
      router.replace("/dashboard");
    }
  }, [session, loading, router]);

  async function signIn() {
    if (isDemoMode()) {
      // No real Supabase/Google in offline demo; auth-provider synthesizes the
      // demo session on first render, so just land on the dashboard.
      router.push("/dashboard");
      return;
    }
    await createClient().auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
        scopes: "https://www.googleapis.com/auth/gmail.send",
        queryParams: { access_type: "offline", prompt: "consent" },
      },
    });
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-md space-y-4 py-20 text-center">
        <Skeleton className="mx-auto h-10 w-64" />
        <Skeleton className="mx-auto h-5 w-80" />
        <Skeleton className="mx-auto h-11 w-48 rounded-full" />
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-5">
        <Link href="/" className="flex items-center gap-2 font-bold tracking-tight">
          <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BookOpenCheck className="size-4" />
          </span>
          LedgerLoop
        </Link>
        <div className="flex items-center gap-3">
          {isDemoMode() && <Badge variant="success">Demo</Badge>}
          <Button variant="outline" onClick={signIn}>
            Sign in
          </Button>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-6">
        <section className="flex flex-1 flex-col items-center justify-center py-16 text-center sm:py-24">
          <Badge variant="neutral" className="mb-5">
            AI finance controller for small shops
          </Badge>
          <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl">
            Your books, reconciled for you.
          </h1>
          <p className="mt-4 max-w-xl text-lg text-muted-foreground">
            Send invoices over Telegram or upload them — LedgerLoop reads them,
            flags anything odd, and emails your CA at month end.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Button onClick={signIn} size="lg">
              <GoogleIcon />
              Sign in with Google
            </Button>
            {isDemoMode() && (
              <Button variant="outline" size="lg" onClick={() => router.push("/dashboard")}>
                Try the demo <ArrowRight className="ml-1.5 size-4" />
              </Button>
            )}
          </div>
          <p className="mt-6 max-w-md text-sm text-muted-foreground">
            Your ledger is private — only you and your CA can see it.
          </p>
        </section>

        <section className="grid gap-4 pb-16 sm:grid-cols-3">
          {FEATURES.map((f) => (
            <Card key={f.title}>
              <CardContent className="p-5">
                <f.icon className="size-6 text-primary" />
                <h3 className="mt-3 font-semibold">{f.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{f.text}</p>
              </CardContent>
            </Card>
          ))}
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2 px-6 py-5 text-sm text-muted-foreground">
          <span>© {new Date().getFullYear()} LedgerLoop</span>
          <div className="flex gap-4">
            <Link href="/privacy" className="hover:text-foreground">
              Privacy
            </Link>
            <Link href="/terms" className="hover:text-foreground">
              Terms
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
