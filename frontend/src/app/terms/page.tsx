import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function Terms() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-3xl font-semibold tracking-tight">Terms of Service</h1>
      <p className="mt-1 text-sm text-muted-foreground">Last updated: August 2026</p>
      <div className="mt-6 space-y-4 text-sm leading-relaxed text-muted-foreground">
        <p>
          By using LedgerLoop you agree to the following, kept deliberately short.
        </p>
        <div>
          <h2 className="font-semibold text-foreground">What LedgerLoop does</h2>
          <p>
            It reads bills you send it, extracts details with AI, reconciles them
            into a monthly ledger, flags anything suspicious, and emails a
            month-end summary to your CA when you tell it to.
          </p>
        </div>
        <div>
          <h2 className="font-semibold text-foreground">Verify before filing</h2>
          <p>
            AI extraction can misread numbers. Always verify extracted amounts
            against your original documents before relying on them for GST filing
            or accounting. LedgerLoop prepares records — it does not file tax
            returns and does not replace your CA&apos;s judgement.
          </p>
        </div>
        <div>
          <h2 className="font-semibold text-foreground">No liability</h2>
          <p>
            LedgerLoop is provided as-is. We are not liable for filing errors,
            penalties, or losses arising from inaccurate extractions. Flagged
            items are shown prominently — please resolve them before treating a
            month as final.
          </p>
        </div>
        <div>
          <h2 className="font-semibold text-foreground">Automated actions are bounded</h2>
          <p>
            Nothing is auto-filed, auto-approved, or sent without your explicit
            action. Every send is logged in an audit trail you can review.
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
