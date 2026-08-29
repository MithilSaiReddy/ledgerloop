import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function Privacy() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-3xl font-semibold tracking-tight">Privacy Policy</h1>
      <p className="mt-1 text-sm text-muted-foreground">Last updated: August 2026</p>
      <div className="mt-6 space-y-4 text-sm leading-relaxed text-muted-foreground">
        <p>
          LedgerLoop helps small business owners keep clean books. We take your
          privacy seriously and keep this policy plain-language.
        </p>
        <div>
          <h2 className="font-semibold text-foreground">What we store</h2>
          <p>
            The invoices you send us (via Telegram or upload), the details we
            extract from them (vendor, amounts, GST breakdown), and your account
            settings (shop name, CA email). Everything is stored in your own
            private database, scoped strictly to your account.
          </p>
        </div>
        <div>
          <h2 className="font-semibold text-foreground">Who can see your data</h2>
          <p>
            Only you (after signing in with Google) and your CA — via the
            month-end summary emails you choose to send. We never sell or share
            your data with anyone else.
          </p>
        </div>
        <div>
          <h2 className="font-semibold text-foreground">Google access</h2>
          <p>
            We request permission to send email on your behalf (Gmail
            &quot;send&quot; scope) so month-end summaries can come from your own
            address. This is used only when you click &quot;Send to CA&quot;. We
            do not read your inbox.
          </p>
        </div>
        <div>
          <h2 className="font-semibold text-foreground">Deleting your data</h2>
          <p>
            Contact us and we will delete all of your data. Removing our app&apos;s
            access in your Google Account settings (
            https://myaccount.google.com/permissions) also revokes our ability to
            send email as you.
          </p>
        </div>
      </div>
      <Link href="/" className="mt-8 inline-block">
        <Button variant="outline" size="sm">
          ← Back to LedgerLoop
        </Button>
      </Link>
    </div>
  );
}
