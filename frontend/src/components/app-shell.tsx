"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import {
  BookOpenCheck,
  LayoutDashboard,
  MailWarning,
  ScrollText,
  Send,
  Sun,
  Moon,
  Settings,
  LogOut,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/components/auth-provider";
import { isDemoMode } from "@/lib/demo";
import { cn } from "@/lib/utils";

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/ledger", label: "Ledger", icon: BookOpenCheck },
  { href: "/exceptions", label: "Exceptions", icon: MailWarning },
  { href: "/audit", label: "Audit", icon: ScrollText },
  { href: "/send", label: "Send to CA", icon: Send },
];

const TITLES: Record<string, string> = Object.fromEntries(
  [...NAV, { href: "/settings", label: "Settings" }].map((n) => [n.href, n.label]),
);

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          aria-label="Toggle theme"
        >
          {resolvedTheme === "dark" ? <Sun /> : <Moon />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>Toggle theme</TooltipContent>
    </Tooltip>
  );
}

function UserMenu() {
  const router = useRouter();
  const { session, signOut } = useAuth();

  async function handleSignOut() {
    await signOut();
    router.push("/");
  }

  const email = session?.user.email ?? "demo@local";
  const name =
    (session?.user.user_metadata?.name as string) ||
    email?.split("@")[0] ||
    "Demo user";
  const initials = name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="rounded-full" aria-label="Account">
          <Avatar className="size-8">
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <div className="flex flex-col">
            <span className="truncate text-sm font-medium">{name}</span>
            <span className="truncate text-xs font-normal text-muted-foreground">{email}</span>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/settings")}>
          <Settings data-icon="inline-start" />
          Settings
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={handleSignOut} variant="destructive">
          <LogOut data-icon="inline-start" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Brand({ className }: { className?: string }) {
  return (
    <Link
      href="/dashboard"
      className={cn(
        "flex items-center gap-2 font-bold tracking-tight",
        className,
      )}
      title="LedgerLoop"
    >
      <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <BookOpenCheck className="size-4" />
      </span>
      <span className="truncate">LedgerLoop</span>
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const title = TITLES[pathname] ?? "";

  const publicRoutes =
    pathname === "/" ||
    pathname === "/onboarding" ||
    pathname === "/privacy" ||
    pathname === "/terms" ||
    pathname.startsWith("/auth");

  if (publicRoutes) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen w-full overflow-x-clip bg-background">
      <SidebarProvider>
        <Sidebar collapsible="icon">
          <SidebarHeader className="p-2 group-data-[collapsible=icon]:p-0">
            <div className="flex items-center justify-between gap-1 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0.5">
              <Brand className="min-w-0 group-data-[collapsible=icon]:hidden" />
              <Link
                href="/dashboard"
                title="LedgerLoop"
                aria-label="LedgerLoop"
                className="hidden size-4 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground group-data-[collapsible=icon]:flex"
              >
                <BookOpenCheck className="size-3.5" />
              </Link>
              <SidebarTrigger
                className="ml-auto size-7 text-sidebar-foreground group-data-[collapsible=icon]:ml-0 group-data-[collapsible=icon]:size-6"
                aria-label="Toggle sidebar"
              />
            </div>
          </SidebarHeader>
          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  {NAV.map((item) => {
                    const active = pathname === item.href;
                    return (
                      <SidebarMenuItem key={item.href}>
                        <SidebarMenuButton asChild isActive={active} tooltip={item.label} size="lg">
                          <Link href={item.href}>
                            <item.icon />
                            <span>{item.label}</span>
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      asChild
                      isActive={pathname === "/settings"}
                      tooltip="Settings"
                      size="lg"
                    >
                      <Link href="/settings">
                        <Settings />
                        <span>Settings</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
        </Sidebar>
        <SidebarInset>
          <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger className="size-9 md:hidden" aria-label="Open menu" />
            <span className="hidden text-base font-semibold tracking-tight sm:block">
              {title}
            </span>
            <div className="ml-auto flex items-center gap-1">
              {isDemoMode() && (
                <Badge variant="success" className="hidden gap-1 sm:inline-flex">
                  <span className="size-1.5 rounded-full bg-success" />
                  Demo
                </Badge>
              )}
              <ThemeToggle />
              <UserMenu />
            </div>
          </header>
          <main className="mx-auto flex min-w-0 w-full max-w-6xl flex-1 flex-col gap-6 p-4 sm:p-6 lg:p-6">{children}</main>
        </SidebarInset>
      </SidebarProvider>
    </div>
  );
}
