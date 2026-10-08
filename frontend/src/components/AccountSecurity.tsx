/** Account → two-step verification (AUTH-9) and Account → preferences (defaults and file names, EXP-6). */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { ApiError, api, errorMessage } from "../api/client";
import type { MfaStatus, Preferences, RecoveryCodes as Codes, Theme } from "../api/types";
import { meKey, useMe, useSetMe } from "../auth/auth";
import { DesignPanel, useTemplates } from "./design";
import { MfaSetup, RecoveryCodes } from "./MfaSetup";
import { Alert, Badge, Button, Card, CardBody, CardHeader, Checkbox, Spinner, TextField } from "./ui";

const mfaKey = ["mfa"] as const;

/** After signing in with a recovery code: how many are left, and how to move to a new phone. The notice comes
 * only with that sign-in, so it stays up (until dismissed) when who's signed in is fetched again. */
export function RecoveryCodeNotice() {
  const used = useMe().data?.notices.includes("recovery-code-used") ?? false;
  const [state, setState] = useState<"waiting" | "shown" | "dismissed">("waiting");
  if (used && state === "waiting") setState("shown");
  const status = useQuery({ queryKey: mfaKey, queryFn: () => api<MfaStatus>("GET", "/api/auth/mfa"), enabled: state === "shown" });
  if (state !== "shown") return null;
  const left = status.data?.recoveryCodesLeft;
  return (
    <Alert tone="warning" title="You signed in with a recovery code" className="mb-6">
      {left !== undefined && `You have ${left} left. `}Lost your phone? On{" "}
      <Link to="/account" className="font-medium underline underline-offset-2">your account page</Link>, turn two-step
      verification off and set it up again on your new phone.{" "}
      <button type="button" className="font-medium underline underline-offset-2" onClick={() => setState("dismissed")}>Dismiss</button>
    </Alert>
  );
}

export function TwoStepCard() {
  const queryClient = useQueryClient();
  const setMe = useSetMe();
  const status = useQuery({ queryKey: mfaKey, queryFn: () => api<MfaStatus>("GET", "/api/auth/mfa") });
  const [mode, setMode] = useState<"idle" | "setup" | "codes" | "regenerate" | "disable">("idle");
  const [codes, setCodes] = useState<string[]>([]);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const reset = () => { setMode("idle"); setPassword(""); setCode(""); setError(null); };
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: mfaKey }), queryClient.invalidateQueries({ queryKey: meKey })]);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, errorMessage(e)));
    } finally {
      setBusy(false);
    }
  };

  const s = status.data;
  return (
    <Card>
      <CardHeader title="Two-step verification"
        description="Signing in asks for a code from an authenticator app as well as your password."
        actions={s?.enabled ? <Badge tone="green"><ShieldCheck className="mr-1 size-3.5" aria-hidden />On</Badge> : s ? <Badge>Off</Badge> : undefined} />
      <CardBody className="space-y-4">
        {status.isPending ? <Spinner /> : !s ? <Alert tone="error">{errorMessage(status.error)}</Alert> : mode === "setup" ? (
          <MfaSetup needsPassword onCancel={reset} onEnabled={(me, recovery) => { setMe(me); setCodes(recovery); setMode("codes"); void refresh(); }} />
        ) : mode === "codes" ? (
          <RecoveryCodes codes={codes} onDone={reset} />
        ) : mode === "regenerate" || mode === "disable" ? (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void run(async () => {
            if (mode === "regenerate") {
              const fresh = await api<Codes>("POST", "/api/auth/mfa/recovery-codes", { json: { password } });
              setCodes(fresh.recoveryCodes);
              setMode("codes");
            } else {
              await api("POST", "/api/auth/mfa/disable", { json: { password, code } });
              reset();
            }
            await refresh();
          }); }}>
            <p className="text-sm text-slate-600 dark:text-slate-400">{mode === "regenerate"
              ? "New codes replace the old ones, which stop working."
              : "Turning it off makes your account easier to break into. Confirm with your password and a code."}</p>
            <TextField label="Your password" type="password" autoComplete="current-password" required value={password}
              onChange={(e) => setPassword(e.target.value)} error={error?.fieldError("password")} />
            {mode === "disable" && (
              <TextField label="Code from your app, or a recovery code" autoComplete="one-time-code" required value={code}
                onChange={(e) => setCode(e.target.value)} error={error?.fieldError("code")} className="max-w-60" />
            )}
            {error && !error.errors.length && <Alert tone="error">{error.message}</Alert>}
            <div className="flex gap-2">
              <Button type="submit" loading={busy} variant={mode === "disable" ? "danger" : "primary"}>
                {mode === "regenerate" ? "Make new codes" : "Turn off"}
              </Button>
              <Button variant="ghost" onClick={reset}>Cancel</Button>
            </div>
          </form>
        ) : s.enabled ? (
          <>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {s.recoveryCodesLeft} of 10 recovery codes left.{s.recoveryCodesLeft <= 3 && " Make new ones soon."}
              {s.required && " Your administrator requires two-step verification."}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" icon={<KeyRound className="size-4" aria-hidden />} onClick={() => setMode("regenerate")}>New recovery codes</Button>
              {!s.required && <Button variant="ghost" size="sm" onClick={() => setMode("disable")}>Turn off</Button>}
            </div>
          </>
        ) : (
          <Button onClick={() => setMode("setup")} icon={<ShieldCheck className="size-4" aria-hidden />}>Set up two-step verification</Button>
        )}
      </CardBody>
    </Card>
  );
}

// ---- preferences ----------------------------------------------------------------------------------------------

const TOKENS = ["{name}", "{first}", "{last}", "{company}", "{role}", "{doc}", "{date}"];

/** What a download would be called: mirrors the server's rules closely enough for a preview. */
export function previewFileName(pattern: string, sample = { name: "Jordan Rivera", company: "Globex", role: "Staff Platform Engineer", doc: "Resume" }): string {
  const slug = (v: string) => v.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  const words = sample.name.split(/\s+/);
  const values: Record<string, string> = { name: slug(sample.name), first: slug(words[0] ?? ""), last: slug(words.length > 1 ? words.at(-1)! : ""),
    company: slug(sample.company), role: slug(sample.role), doc: sample.doc, date: new Date().toISOString().slice(0, 10) };
  let out = pattern.replace(/\{(\w+)\}/g, (_, key: string) => values[key] ?? "");
  out = out.replace(/[^A-Za-z0-9._ ,()-]+/g, "").replace(/([_ .,-])\1+/g, "$1").replace(/\(\s*\)/g, "").replace(/^[_ .,-]+|[_ .,-]+$/g, "");
  return `${out || sample.doc}.pdf`;
}

export function PreferencesCard() {
  const prefs = useQuery({ queryKey: ["preferences"], queryFn: () => api<Preferences>("GET", "/api/account/preferences") });
  const catalog = useTemplates();
  if (prefs.isPending || catalog.isPending) return <Card><CardHeader title="Preferences" /><CardBody><Spinner /></CardBody></Card>;
  if (!prefs.data || !catalog.data) return null;
  return <PreferencesForm initial={prefs.data} defaultTheme={catalog.data.defaultTheme} defaultTemplate={catalog.data.defaultTemplate} />;
}

function PreferencesForm({ initial, defaultTheme, defaultTemplate }: { initial: Preferences; defaultTheme: Theme; defaultTemplate: string }) {
  const queryClient = useQueryClient();
  const [prefs, setPrefs] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const own = prefs.design;
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await api<Preferences>("PUT", "/api/account/preferences", { json: prefs });
      queryClient.setQueryData(["preferences"], out);
      setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, errorMessage(e)));
    } finally {
      setBusy(false);
    }
  };
  const change = (patch: Partial<Preferences>) => { setSaved(false); setPrefs((p) => ({ ...p, ...patch })); };
  return (
    <Card>
      <CardHeader title="Preferences" description="Defaults for new applications, and how downloads are named." />
      <CardBody className="space-y-5">
        <Checkbox label="Write a cover letter with each new application" checked={prefs.coverLetter} onChange={(e) => change({ coverLetter: e.target.checked })} />
        <div>
          <Checkbox label="Use my own template and theme for new applications" checked={Boolean(own)}
            onChange={(e) => change({ design: e.target.checked ? { template: defaultTemplate, theme: defaultTheme } : null })} />
          {!own && <p className="mt-1 pl-6 text-xs text-slate-500 dark:text-slate-400">Otherwise new applications use your instance's default.</p>}
          {own && (
            <div className="mt-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <DesignPanel template={own.template} theme={own.theme} onChange={(template, theme) => change({ design: { template, theme } })} />
            </div>
          )}
        </div>
        <div>
          <TextField label="File names" value={prefs.fileName} maxLength={120} onChange={(e) => change({ fileName: e.target.value })}
            error={error?.fieldError("fileName")}
            hint={<>Use {TOKENS.map((t, i) => <span key={t}><code className="rounded bg-slate-100 px-1 text-slate-700 dark:bg-slate-800 dark:text-slate-300">{t}</code>{i < TOKENS.length - 1 ? " " : ""}</span>)}. For example: <b>{previewFileName(prefs.fileName)}</b></>} />
        </div>
        {error && !error.errors.length && <Alert tone="error">{error.message}</Alert>}
        <div className="flex items-center gap-3">
          <Button onClick={() => void save()} loading={busy}>Save preferences</Button>
          {saved && <span className="text-sm text-emerald-700 dark:text-emerald-400">Saved.</span>}
        </div>
      </CardBody>
    </Card>
  );
}
