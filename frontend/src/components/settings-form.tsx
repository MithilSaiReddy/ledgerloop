"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/components/auth-provider";
import { BUSINESS_TYPES, defaultGstRate, GST_STATES, getUserSettings, saveUserSettings } from "@/lib/api";

/** Shared form for onboarding (/onboarding) and editing later (/settings). */
export function SettingsForm({ mode }: { mode: "onboarding" | "settings" }) {
  const router = useRouter();
  const { session, loading } = useAuth();
  // null = untouched, so Google-profile prefill keeps flowing through until
  // the user actually types something.
  const [shopNameInput, setShopNameInput] = useState<string | null>(null);
  const [caEmailInput, setCaEmailInput] = useState<string | null>(null);
  const [gstin, setGstin] = useState("");
  const [stateCode, setStateCode] = useState<string>("");
  const [address, setAddress] = useState("");
  const [gstRegistered, setGstRegistered] = useState(false);
  const [telegramChatId, setTelegramChatId] = useState("");
  const [defaultRate, setDefaultRate] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const meta = (session?.user.user_metadata ?? {}) as Record<string, string>;
  const shopName = shopNameInput ?? meta.shop_name ?? meta.name ?? "";
  const caEmail = caEmailInput ?? meta.email ?? "";

  useEffect(() => {
    if (!loading && !session) {
      router.replace("/");
      return;
    }
    if (!loading && session && mode === "settings") {
      let cancelled = false;
      getUserSettings(session.access_token)
        .then((s) => {
          if (cancelled) return;
          if (!s) {
            router.replace("/onboarding");
            return;
          }
          setShopNameInput((prev) => prev ?? s.shop_name);
          setCaEmailInput((prev) => prev ?? s.ca_email);
          setGstin(s.gstin ?? "");
          setStateCode(s.state_code ?? "");
          setAddress(s.address ?? "");
          setGstRegistered(s.gst_registered ?? false);
          setTelegramChatId(s.telegram_chat_id ?? "");
          const saved = defaultGstRate(s);
          setDefaultRate(saved !== null ? String(saved) : "");
        })
        .catch(() => toast.error("Couldn't load your settings. Is the backend running?"));
      return () => {
        cancelled = true;
      };
    }
  }, [session, loading, mode, router]);

  const selectedState = GST_STATES.find((s) => s.code === stateCode);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const parsedDefault = Number(defaultRate);
      const tax_rates: Record<string, number> =
        defaultRate.trim() !== "" && Number.isFinite(parsedDefault) && parsedDefault >= 0
          ? { default: parsedDefault }
          : {};
      await saveUserSettings(
        {
          shop_name: shopName,
          ca_email: caEmail,
          gstin,
          state: selectedState?.name ?? "",
          state_code: stateCode,
          address,
          gst_registered: gstRegistered,
          telegram_chat_id: telegramChatId,
          tax_rates: Object.keys(tax_rates).length ? tax_rates : undefined,
        },
        session.access_token,
      );
      toast.success(mode === "onboarding" ? "You're all set!" : "Settings saved");
      router.push("/upload");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto w-full max-w-md">
      <CardContent className="gap-5">
        <form onSubmit={submit} className="flex flex-col gap-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {mode === "onboarding"
              ? `Welcome${shopName ? `, ${shopName.split(" ")[0]}` : ""}! 👋`
              : "Settings"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "onboarding"
              ? "Let's set up your shop — takes 30 seconds."
              : "Update your shop details anytime."}
          </p>
        </div>

      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="shop_name">Shop name</FieldLabel>
          <Input
            id="shop_name"
            required
            placeholder="e.g. Mithil Kirana Store"
            value={shopName}
            onChange={(e) => setShopNameInput(e.target.value)}
          />
        </Field>

        <Field>
          <FieldLabel htmlFor="gst_registered">
            <span>{"I'm GST-registered"}</span>
            <span className="block text-xs font-normal text-muted-foreground">
              Turn on if you charge GST on your bills.
            </span>
          </FieldLabel>
          <Switch
            id="gst_registered"
            checked={gstRegistered}
            onCheckedChange={setGstRegistered}
          />
        </Field>

        <Field>
          <FieldLabel htmlFor="gstin">GSTIN</FieldLabel>
          <Input
            id="gstin"
            placeholder="e.g. 27ABCDE1234F1Z5"
            value={gstin}
            disabled={!gstRegistered}
            onChange={(e) => setGstin(e.target.value.toUpperCase())}
          />
          <FieldDescription>
            {gstRegistered
              ? "Used to tell intra-state from inter-state tax treatment."
              : "Add your GSTIN if you're registered."}
          </FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor="state">Home state</FieldLabel>
          <Select value={stateCode} onValueChange={setStateCode}>
            <SelectTrigger id="state" className="w-full">
              <SelectValue placeholder="Select your state" />
            </SelectTrigger>
            <SelectContent>
              {GST_STATES.map((s) => (
                <SelectItem key={s.code} value={s.code}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FieldDescription>
            Used to work out intra- vs inter-state GST on each bill.
          </FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor="default_rate">Default GST rate</FieldLabel>
          <FieldDescription>
            When a sale bill shows no tax, LedgerLoop adds CGST and SGST at this
            one rate. Pick your business type or type your own — change it anytime.
          </FieldDescription>
          <ToggleGroup
            type="single"
            value={defaultRate}
            onValueChange={(v) => v && setDefaultRate(v)}
            disabled={!gstRegistered}
            className="flex flex-wrap"
          >
            {BUSINESS_TYPES.map((b) => (
              <ToggleGroupItem key={b.key} value={String(b.rate)}>
                {b.label} · {b.rate}%
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
            <Input
              id="default_rate"
              type="number"
              min={0}
              step={0.5}
              inputMode="decimal"
              placeholder="e.g. 5"
              value={defaultRate}
              disabled={!gstRegistered}
              onChange={(e) => setDefaultRate(e.target.value)}
              className="w-full sm:w-32"
            />
            <p className="text-xs text-muted-foreground">
              {gstRegistered
                ? "Clothing up to ₹2,500/piece is 5%; above that it's 18%."
                : "Turn on GST registration above to set a rate."}
            </p>
          </div>
        </Field>

        <Field>
          <FieldLabel htmlFor="address">Business address</FieldLabel>
          <Textarea
            id="address"
            placeholder="Shop no., street, city, PIN"
            rows={2}
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
        </Field>

        <Field>
          <FieldLabel htmlFor="ca_email">CA email</FieldLabel>
          <Input
            id="ca_email"
            type="email"
            required
            placeholder="your-ca@accountant.com"
            value={caEmail}
            onChange={(e) => setCaEmailInput(e.target.value)}
          />
          <FieldDescription>
            Month-end ledger summaries are emailed here.
          </FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor="telegram_chat_id">
            Telegram chat ID <span className="text-muted-foreground">(optional)</span>
          </FieldLabel>
          <Input
            id="telegram_chat_id"
            placeholder="e.g. 123456789"
            value={telegramChatId}
            onChange={(e) => setTelegramChatId(e.target.value)}
          />
          <FieldDescription>
            Used for invoice notifications when you send invoices to the bot.
          </FieldDescription>
        </Field>
      </FieldGroup>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Button type="submit" size="lg" className="w-full" disabled={busy || loading || !session}>
        {busy ? "Saving…" : mode === "onboarding" ? "Start using LedgerLoop →" : "Save changes"}
      </Button>

      {mode === "onboarding" && (
        <p className="text-center text-xs text-muted-foreground">
          Your data stays private — only you and your CA can see it.
        </p>
      )}
        </form>
      </CardContent>
    </Card>
  );
}
