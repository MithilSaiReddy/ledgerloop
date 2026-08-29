import { UploadZone } from "@/components/upload-zone";

export default function UploadPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Add invoices</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          We read each invoice, check it for mistakes, and file the good ones
          automatically. Anything suspicious lands in your review queue.
        </p>
      </div>
      <UploadZone />
    </div>
  );
}
