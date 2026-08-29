"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { UploadZone } from "@/components/upload-zone";

/** Modal wrapper around the uploader so any page can accept invoices inline. */
export function UploadDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add an invoice</DialogTitle>
          <DialogDescription>
            Drop or pick a bill — we&apos;ll file it under the right month automatically.
          </DialogDescription>
        </DialogHeader>
        <UploadZone compact />
      </DialogContent>
    </Dialog>
  );
}
