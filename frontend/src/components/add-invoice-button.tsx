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
        <Plus className="mr-1.5 size-4" />
        {label}
      </Button>
      <UploadDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
