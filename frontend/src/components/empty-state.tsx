import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("py-12 text-center", className)}>
      <CardContent className="flex flex-col items-center gap-2">
        {Icon && (
          <div className="rounded-full bg-muted p-3 text-muted-foreground">
            <Icon className="size-6" />
          </div>
        )}
        <p className="text-sm font-medium text-foreground">{title}</p>
        {description && (
          <p className="max-w-sm text-sm text-muted-foreground">{description}</p>
        )}
        {action && <div className="mt-2">{action}</div>}
      </CardContent>
    </Card>
  );
}
