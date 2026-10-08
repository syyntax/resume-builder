/** Setting up two-step verification (AUTH-9): scan a QR code or type the key, confirm with a code, then save the
 * recovery codes. Used on the Account page and when it's required at sign-in. */

import { Check, Copy, Download } from "lucide-react";
import { useState } from "react";

import { ApiError, api, errorMessage } from "../api/client";
import type { Me, MfaEnabled, MfaSetup as Setup } from "../api/types";
import { Alert, Button, TextField } from "./ui";

export function RecoveryCodes({ codes, onDone, doneLabel = "I've saved them" }: { codes: string[]; onDone?: () => void; doneLabel?: string }) {
  const [copied, setCopied] = useState(false);
  const text = codes.join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([`Resume Tailor recovery codes\nEach works once.\n\n${text}\n`], { type: "text/plain" }));
    const link = Object.assign(document.createElement("a"), { href: url, download: "resume-tailor-recovery-codes.txt" });
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600 dark:text-slate-400">
        If you lose your phone, each of these codes signs you in once. Keep them somewhere safe, like a password manager. They won't be shown again.
      </p>
      <ul className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-lg bg-slate-50 p-3 font-mono text-sm dark:bg-slate-800/60" aria-label="Recovery codes">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" icon={copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
          onClick={() => void navigator.clipboard?.writeText(text).then(() => setCopied(true))}>{copied ? "Copied" : "Copy"}</Button>
        <Button size="sm" variant="secondary" icon={<Download className="size-4" aria-hidden />} onClick={download}>Download</Button>
        {onDone && <Button size="sm" onClick={onDone}>{doneLabel}</Button>}
      </div>
    </div>
  );
}

/** `needsPassword`: false while finishing a sign-in that requires it (the password was just entered). */
export function MfaSetup({ needsPassword, onEnabled, onCancel }: { needsPassword: boolean; onEnabled: (me: Me, codes: string[]) => void; onCancel?: () => void }) {
  const [password, setPassword] = useState("");
  const [setup, setSetup] = useState<Setup | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(errorMessage(e)));
    } finally {
      setBusy(false);
    }
  };
  const fieldError = (field: string) => (error instanceof ApiError ? error.fieldError(field) : undefined);
  const generalError = error && !(error instanceof ApiError && error.errors.length) ? errorMessage(error) : null;
  // the server asks for the password unless signing in just did (it then says so with a field error)
  const [askPassword, setAskPassword] = useState(needsPassword);
  if (!askPassword && fieldError("password")) setAskPassword(true);

  if (!setup) {
    return (
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void run(async () => {
        setSetup(await api<Setup>("POST", "/api/auth/mfa/setup", { json: askPassword ? { password } : {} }));
      }); }}>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          You'll need an authenticator app, such as 1Password, Google Authenticator, Microsoft Authenticator or Authy.
        </p>
        {askPassword && (
          <TextField label="Your password" type="password" autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} error={password ? fieldError("password") : undefined} />
        )}
        {generalError && <Alert tone="error">{generalError}</Alert>}
        <div className="flex gap-2">
          <Button type="submit" loading={busy}>Start</Button>
          {onCancel && <Button variant="ghost" onClick={onCancel}>Cancel</Button>}
        </div>
      </form>
    );
  }

  const key = setup.secret.match(/.{1,4}/g)?.join(" ") ?? setup.secret;
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void run(async () => {
      const done = await api<MfaEnabled>("POST", "/api/auth/mfa/enable", { json: { code } });
      onEnabled(done.me, done.recoveryCodes);
    }); }}>
      <ol className="list-decimal space-y-3 pl-5 text-sm text-slate-700 dark:text-slate-300">
        <li>
          Scan this code with your authenticator app:
          <img src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(setup.qrSvg)}`} alt="QR code for your authenticator app"
            className="mt-2 size-44 rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-700" />
          <span className="mt-2 block text-xs text-slate-500 dark:text-slate-400">Can't scan it? Enter this key instead: <code className="font-mono text-slate-800 select-all dark:text-slate-200">{key}</code></span>
        </li>
        <li>Enter the 6-digit code the app shows.</li>
      </ol>
      <TextField label="Code" inputMode="numeric" autoComplete="one-time-code" required maxLength={8} value={code}
        onChange={(e) => setCode(e.target.value)} error={fieldError("code")} className="max-w-40" />
      {generalError && <Alert tone="error">{generalError}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" loading={busy}>Turn on</Button>
        {onCancel && <Button variant="ghost" onClick={onCancel}>Cancel</Button>}
      </div>
    </form>
  );
}
