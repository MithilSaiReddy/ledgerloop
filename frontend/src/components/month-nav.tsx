"use client";

import { useRouter } from "next/navigation";
import { CalendarDays } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/**
 * Client month selector that navigates to the given path with ?month=... .
 * Extra search params (key/value pairs) are preserved/merged.
 */
export function MonthNav({
  path,
  months,
  value,
  extra,
}: {
  path: string;
  months: string[];
  value: string;
  extra?: Record<string, string>;
}) {
  const router = useRouter();

  function onSelect(next: string) {
    const params = new URLSearchParams(extra ?? {});
    params.set("month", next);
    router.push(`${path}?${params.toString()}`);
  }

  return (
    <Select value={value} onValueChange={onSelect}>
      <SelectTrigger className="w-[190px]">
        <CalendarDays className="mr-2 size-4 opacity-50" />
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {months.map((m) => (
          <SelectItem key={m} value={m}>
            {m}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
