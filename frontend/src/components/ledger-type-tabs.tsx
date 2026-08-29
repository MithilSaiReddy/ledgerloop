"use client";

import { useRouter } from "next/navigation";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function LedgerTypeTabs({
  month,
  value,
  counts,
}: {
  month: string;
  value: "all" | "purchase" | "sale";
  counts: { all: number; purchase: number; sale: number };
}) {
  const router = useRouter();

  return (
    <Tabs
      value={value}
      onValueChange={(v) => router.push(`/ledger?month=${month}&type=${v}`)}
    >
      <TabsList>
        <TabsTrigger value="all">All ({counts.all})</TabsTrigger>
        <TabsTrigger value="purchase">Purchases ({counts.purchase})</TabsTrigger>
        <TabsTrigger value="sale">Sales ({counts.sale})</TabsTrigger>
      </TabsList>
    </Tabs>
  );
}
