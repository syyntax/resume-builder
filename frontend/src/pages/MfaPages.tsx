/** The second step of signing in (a code from the authenticator, or a recovery code), and setting it up when an
 * admin requires it. Shown in place of the app until signing in is complete. */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { Me } from "../api/types";
import { useMe, useSetMe, useSignOut } from "../auth/auth";
import { MfaSetup, RecoveryCodes } from "../components/MfaSetup";
import { Alert, Button, TextField } from "../components/ui";
import { AuthLayout } from "../layouts/AuthLayout";

function SignOutLink() {
  const signOut = useSignOut();
  return (
    <button type="button" className="font-medium text-brand-600 hover:underline dark:text-brand-300" onClick={() => signOut.mutate()}>
      Sign in as someone else
    </button>
  );
}

export function MfaChallengePage() {
  const setMe = useSetMe();
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const verify = useMutation({
    mutationFn: () => api<Me>("POST", "/api/auth/mfa/verify", { json: { code } }),
    onSuccess: (me) => setMe(me),
  });
  const error = verify.error instanceof ApiError ? verify.error.message : verify.error ? "Something went wrong. Try again." : null;
  return (
    <AuthLayout title="Two-step verification" subtitle={recovery ? "Enter one of your recovery codes." : "Enter the code from your authenticator app."}
      footer={<SignOutLink />}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); verify.mutate(); }}>
        {error && <Alert tone="error">{error}</Alert>}
        {recovery ? (
          <TextField key="recovery" label="Recovery code" autoComplete="off" autoFocus required value={code} placeholder="xxxx-xxxx-xx"
            onChange={(e) => setCode(e.target.value)} />
        ) : (
          <TextField key="code" label="Code" inputMode="numeric" autoComplete="one-time-code" autoFocus required maxLength={8} value={code}
            onChange={(e) => setCode(e.target.value)} />
        )}
        <Button type="submit" className="w-full" loading={verify.isPending}>Verify</Button>
        <button type="button" className="w-full text-center text-sm text-slate-500 dark:text-slate-400 hover:underline" onClick={() => { setRecovery((r) => !r); setCode(""); verify.reset(); }}>
          {recovery ? "Use the authenticator app instead" : "Lost your phone? Use a recovery code"}
        </button>
      </form>
    </AuthLayout>
  );
}

export function MfaEnrollPage() {
  const me = useMe().data;
  const setMe = useSetMe();
  const [done, setDone] = useState<{ me: Me; codes: string[] } | null>(null);
  return (
    <AuthLayout title="Set up two-step verification"
      subtitle={done ? "One more thing: your recovery codes." : "Your administrator requires it. It takes a minute."}
      footer={<SignOutLink />}>
      {done ? (
        <RecoveryCodes codes={done.codes} doneLabel="Continue" onDone={() => setMe(done.me)} />
      ) : (
        <MfaSetup needsPassword={false} onEnabled={(next, codes) => setDone({ me: next, codes })} />
      )}
      {me && !done && <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">Signed in as {me.user.email}.</p>}
    </AuthLayout>
  );
}
