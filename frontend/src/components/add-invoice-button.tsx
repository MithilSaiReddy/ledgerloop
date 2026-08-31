"use client";

import { useState } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { UploadDialog } from "@/components/upload-dialog";

export function AddInvoiceButton({ label = "Add an invoice" }: { label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <Plus data-icon="inline-start" />
        {label}
      </Button>
      <UploadDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
