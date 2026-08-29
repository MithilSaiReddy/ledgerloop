"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowRight, CloudUpload, FileText, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/auth-provider";
import { reasonLabel, uploadInvoice, type IngestResult } from "@/lib/api";
import { cn } from "@/lib/utils";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff,.tif,.txt,.docx,.xlsx,.html,.eml,.csv";

interface FileState {
  name: string;
  status: "uploading" | "done" | "error";
  result?: IngestResult;
  error?: string;
}

export function UploadZone({ compact = false }: { compact?: boolean }) {
  const router = useRouter();
  const { session } = useAuth();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<FileState[]>([]);

  const handleFiles = useCallback(
    async (list: FileList | File[]) => {
      const token = session?.access_token;
      if (!token) {
        toast.error("Please sign in first");
        router.push("/");
        return;
      }
      const incoming = Array.from(list);
      setFiles((prev) => [
        ...prev,
        ...incoming.map((f) => ({ name: f.name, status: "uploading" as const })),
      ]);
      for (const file of incoming) {
        try {
          const result = await uploadInvoice(file, token);
          setFiles((prev) =>
            prev.map((f) =>
              f.name === file.name ? { name: f.name, status: "done", result } : f,
            ),
          );
          if (result.status === "ledger") {
            toast.success(result.message);
          } else {
            toast.warning(result.message);
          }
        } catch (e) {
          const msg = e instanceof Error ? e.message : "Upload failed";
          setFiles((prev) =>
            prev.map((f) =>
              f.name === file.name ? { name: f.name, status: "error", error: msg } : f,
            ),
          );
          toast.error(msg);
        }
      }
      router.refresh();
    },
    [session, router],
  );

  return (
    <div className="space-y-4">
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload invoices"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) void handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center transition-colors",
          compact ? "min-h-40" : "min-h-56",
          dragging
            ? "border-ring bg-muted"
            : "border-border bg-card hover:border-ring/70 hover:bg-muted/40",
        )}
      >
        <div className="rounded-full bg-muted p-3 text-muted-foreground">
          <CloudUpload className="size-8" />
        </div>
        <p className="mt-3 font-medium">Drop invoice files here</p>
        <p className="mt-1 text-sm text-muted-foreground">
          or tap to browse · PDF, photo, or scan · up to 10 MB
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) void handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {files.length > 0 && (
        <ul className="divide-y overflow-hidden rounded-xl border bg-card">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-3 px-4 py-3">
              <FileIcon status={f.status} />
              <span className="min-w-0 flex-1 truncate text-sm">{f.name}</span>
              {f.status === "uploading" && (
                <span className="text-xs text-muted-foreground">processing…</span>
              )}
              {f.status === "done" && f.result && (
                <span className="max-w-[55%] truncate text-right text-xs">
                  {f.result.status === "ledger" ? (
                    <span className="font-medium text-success">{f.result.message}</span>
                  ) : f.result.status === "exception" ? (
                    <span className="font-medium text-warning">
                      Needs review — {reasonLabel(f.result.reason ?? "")}
                    </span>
                  ) : (
                    <span className="font-medium text-destructive">{f.result.detail}</span>
                  )}
                </span>
              )}
              {f.status === "error" && (
                <span className="truncate text-xs text-destructive">{f.error}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {!compact && (
        <div className="flex justify-end">
          <Button variant="outline" onClick={() => router.push("/ledger")}>
            Go to ledger
            <ArrowRight className="ml-1.5 size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}

function FileIcon({ status }: { status: FileState["status"] }) {
  if (status === "uploading") {
    return <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />;
  }
  return (
    <FileText
      className={cn(
        "size-4 shrink-0",
        status === "done" ? "text-success" : "text-destructive",
      )}
    />
  );
}
