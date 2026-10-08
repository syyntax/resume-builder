import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError, api } from "../api/client";
import type { Me, TokenCheck, VerificationSent } from "../api/types";
import { registrationKey, useRegistrationInfo, useSetMe } from "../auth/auth";
import { PasswordFields } from "../components/PasswordFields";
import { Alert, Button, Checkbox, FullPageSpinner, TextField } from "../components/ui";
import { AuthLayout } from "../layouts/AuthLayout";

function safeNext(next: string | null): string {
  // Only allow same-app paths, never absolute URLs (avoids open redirects).
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.message : "Something went wrong. Try again.";
  return <Alert tone="error">{message}</Alert>;
}

// ---- first-run setup ---------------------------------------------------------------------------------

export function SetupPage() {
  const registration = useRegistrationInfo();
  const setMe = useSetMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState({ token: "", displayName: "", email: "", password: "", confirm: "" });

  const setup = useMutation({
    mutationFn: () =>
      api<Me>("POST", "/api/auth/setup", {
        json: { token: form.token, displayName: form.displayName, email: form.email, password: form.password },
      }),
    onSuccess: (me) => {
      setMe(me);
      void queryClient.invalidateQueries({ queryKey: registrationKey });
      navigate("/", { replace: true });
    },
  });

  if (registration.isPending) return <FullPageSpinner />;
  if (registration.data && !registration.data.needsSetup) return <Navigate to="/login" replace />;

  const error = setup.error instanceof ApiError ? setup.error : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (form.password === form.confirm) setup.mutate();
  };

  return (
    <AuthLayout
      title="Set up Resume Tailor"
      subtitle="Create the first account. It will be the admin for this deployment."
    >
      <form onSubmit={submit} className="space-y-4">
        <FormError error={setup.error && !error?.errors.length ? setup.error : null} />
        <TextField
          label="Setup token"
          required
          autoComplete="off"
          value={form.token}
          onChange={(e) => setForm({ ...form, token: e.target.value.trim() })}
          error={setup.error && error?.status === 400 ? error.message : undefined}
          hint={
            <>
              Printed in the server log on first start. Run{" "}
              <code className="rounded bg-slate-100 px-1 text-slate-700 dark:bg-slate-800 dark:text-slate-300">docker compose logs app | grep "Setup token"</code>
            </>
          }
        />
        <TextField label="Your name" required autoComplete="name" value={form.displayName}
          onChange={(e) => setForm({ ...form, displayName: e.target.value })} />
        <TextField label="Email" type="email" required autoComplete="email" value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })} error={error?.fieldError("email")} />
        <PasswordFields
          password={form.password}
          confirm={form.confirm}
          onPassword={(password) => setForm({ ...form, password })}
          onConfirm={(confirm) => setForm({ ...form, confirm })}
          error={error?.errors.filter((x) => x.field === "password").map((x) => x.message).join(" ") || undefined}
        />
        <Button type="submit" className="w-full" loading={setup.isPending}>
          Create admin account
        </Button>
      </form>
    </AuthLayout>
  );
}

// ---- sign in -------------------------------------------------------------------------------------------

export function LoginPage() {
  const [params] = useSearchParams();
  const registration = useRegistrationInfo();
  const setMe = useSetMe();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: "", password: "", remember: false });

  const login = useMutation({
    mutationFn: () => api<Me>("POST", "/api/auth/login", { json: form }),
    onSuccess: (me) => {
      setMe(me);
      navigate(safeNext(params.get("next")), { replace: true });
    },
  });

  const mode = registration.data?.mode;
  return (
    <AuthLayout
      title="Sign in"
      subtitle="Welcome back."
      footer={
        mode === "open" ? (
          <>
            New here?{" "}
            <Link to="/register" className="font-medium text-brand-600 hover:underline dark:text-brand-300">
              Create an account
            </Link>
          </>
        ) : mode === "invite" ? (
          "New here? Ask an admin for an invite link."
        ) : null
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate();
        }}
        className="space-y-4"
      >
        <FormError error={login.error} />
        <TextField label="Email" type="email" required autoComplete="username" autoFocus value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <TextField label="Password" type="password" required autoComplete="current-password" value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <div className="flex items-center justify-between">
          <Checkbox label="Keep me signed in" checked={form.remember}
            onChange={(e) => setForm({ ...form, remember: e.target.checked })} />
        </div>
        <Button type="submit" className="w-full" loading={login.isPending}>
          Sign in
        </Button>
        {registration.data?.emailEnabled ? (
          <p className="text-center text-sm">
            <Link to="/forgot-password" className="font-medium text-brand-600 hover:underline dark:text-brand-300">Forgot your password?</Link>
          </p>
        ) : (
          <p className="text-center text-xs text-slate-500 dark:text-slate-400">Forgot your password? Ask an admin for a reset link.</p>
        )}
      </form>
    </AuthLayout>
  );
}

// ---- registration (open mode, or via an invite link) ------------------------------------------------

export function RegisterPage() {
  const { token } = useParams();
  const registration = useRegistrationInfo();
  const invite = useQuery({
    queryKey: ["invite", token],
    queryFn: () => api<TokenCheck>("GET", `/api/auth/invites/${encodeURIComponent(token ?? "")}`),
    enabled: Boolean(token),
    retry: false,
  });
  const setMe = useSetMe();
  const navigate = useNavigate();
  const [form, setForm] = useState({ displayName: "", email: "", password: "", confirm: "" });

  const register = useMutation({
    mutationFn: () =>
      api<Me | VerificationSent>("POST", "/api/auth/register", {
        json: {
          displayName: form.displayName,
          email: invite.data?.email ?? form.email,
          password: form.password,
          ...(token ? { inviteToken: token } : {}),
        },
      }),
    onSuccess: (result) => {
      if ("verificationSent" in result) return; // shown below: check your email
      setMe(result);
      navigate("/", { replace: true });
    },
  });

  if (registration.isPending || (token && invite.isPending)) return <FullPageSpinner />;
  if (register.data && "verificationSent" in register.data) {
    return (
      <AuthLayout title="Check your email" footer={<Link to="/login" className="font-medium text-brand-600 hover:underline dark:text-brand-300">Go to sign in</Link>}>
        <div className="flex gap-3 text-sm text-slate-700 dark:text-slate-300">
          <MailCheck className="mt-0.5 size-5 shrink-0 text-brand-600 dark:text-brand-300" aria-hidden />
          <p>We've sent a link to <b>{register.data.email}</b>. Open it to confirm your address, then sign in. It works for 24 hours.</p>
        </div>
      </AuthLayout>
    );
  }
  const signIn = (
    <Link to="/login" className="font-medium text-brand-600 hover:underline dark:text-brand-300">
      Sign in
    </Link>
  );

  if (token && !invite.data?.valid) {
    return (
      <AuthLayout title="This invite link doesn't work" footer={<>Already have an account? {signIn}</>}>
        <Alert tone="warning">It may have expired or already been used. Ask your admin for a new invite.</Alert>
      </AuthLayout>
    );
  }
  const mode = registration.data?.mode;
  if (!token && mode !== "open") {
    return (
      <AuthLayout title="Registration is not open" footer={<>Already have an account? {signIn}</>}>
        <Alert tone="info">
          {mode === "invite"
            ? "This deployment is invite-only. Ask an admin for an invite link."
            : "New accounts are created by an admin. Ask them for access."}
        </Alert>
      </AuthLayout>
    );
  }

  const error = register.error instanceof ApiError ? register.error : null;
  return (
    <AuthLayout
      title={token ? "You're invited" : "Create your account"}
      subtitle={registration.data?.domainRestricted && !token ? "Use your work email address." : undefined}
      footer={<>Already have an account? {signIn}</>}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (form.password === form.confirm) register.mutate();
        }}
        className="space-y-4"
      >
        <FormError error={register.error && !error?.errors.length ? register.error : null} />
        <TextField label="Your name" required autoComplete="name" value={form.displayName}
          onChange={(e) => setForm({ ...form, displayName: e.target.value })} />
        <TextField
          label="Email"
          type="email"
          required
          autoComplete="email"
          value={invite.data?.email ?? form.email}
          disabled={Boolean(invite.data?.email)}
          hint={invite.data?.email ? "This invite is for this address." : undefined}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          error={error?.fieldError("email")}
        />
        <PasswordFields
          password={form.password}
          confirm={form.confirm}
          onPassword={(password) => setForm({ ...form, password })}
          onConfirm={(confirm) => setForm({ ...form, confirm })}
          error={error?.errors.filter((x) => x.field === "password").map((x) => x.message).join(" ") || undefined}
        />
        <Button type="submit" className="w-full" loading={register.isPending}>
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}

// ---- forgot password (when email is set up) and confirming an address ------------------------------------

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const forgot = useMutation({ mutationFn: () => api<void>("POST", "/api/auth/password/forgot", { json: { email } }) });
  const back = <Link to="/login" className="font-medium text-brand-600 hover:underline dark:text-brand-300">Back to sign in</Link>;
  if (forgot.isSuccess) {
    return (
      <AuthLayout title="Check your email" footer={back}>
        <Alert tone="success">If {email} has an account, a reset link is on its way. It works for 30 minutes.</Alert>
      </AuthLayout>
    );
  }
  return (
    <AuthLayout title="Reset your password" subtitle="We'll email you a link to choose a new one." footer={back}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); forgot.mutate(); }}>
        <FormError error={forgot.error} />
        <TextField label="Email" type="email" required autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        <Button type="submit" className="w-full" loading={forgot.isPending}>Send reset link</Button>
      </form>
    </AuthLayout>
  );
}

export function VerifyEmailPage() {
  const { token = "" } = useParams();
  const verify = useMutation({ mutationFn: () => api<void>("POST", "/api/auth/verify-email", { json: { token } }) });
  const started = useRef(false);
  useEffect(() => {
    if (!started.current) {
      started.current = true; // once, even in development's double effects
      verify.mutate();
    }
  }, [verify]);
  const signIn = <Link to="/login" className="font-medium text-brand-600 hover:underline dark:text-brand-300">Go to sign in</Link>;
  if (verify.isSuccess) {
    return <AuthLayout title="Email confirmed" footer={signIn}><Alert tone="success">Thanks. You can sign in now.</Alert></AuthLayout>;
  }
  if (verify.isError) {
    return (
      <AuthLayout title="This link doesn't work" footer={signIn}>
        <Alert tone="warning">{verify.error instanceof ApiError ? verify.error.message : "Something went wrong. Try the link again, or sign in to get a new one."}</Alert>
      </AuthLayout>
    );
  }
  return <FullPageSpinner />;
}

// ---- password reset (from an emailed or admin-generated link) -----------------------------------------

export function ResetPasswordPage() {
  const { token = "" } = useParams();
  const check = useQuery({
    queryKey: ["reset", token],
    queryFn: () => api<TokenCheck>("GET", `/api/auth/password-reset/${encodeURIComponent(token)}`),
    retry: false,
  });
  const [form, setForm] = useState({ password: "", confirm: "" });
  const reset = useMutation({
    mutationFn: () => api<void>("POST", "/api/auth/password-reset", { json: { token, newPassword: form.password } }),
  });

  if (check.isPending) return <FullPageSpinner />;
  const signIn = (
    <Link to="/login" className="font-medium text-brand-600 hover:underline dark:text-brand-300">
      Go to sign in
    </Link>
  );
  if (reset.isSuccess) {
    return (
      <AuthLayout title="Password updated" footer={signIn}>
        <Alert tone="success">Your password was changed and you were signed out everywhere. Sign in with the new password.</Alert>
      </AuthLayout>
    );
  }
  if (!check.data?.valid) {
    return (
      <AuthLayout title="This reset link doesn't work" footer={signIn}>
        <Alert tone="warning">Reset links expire after 30 minutes and work once. Request a new one, or ask an admin.</Alert>
      </AuthLayout>
    );
  }
  const error = reset.error instanceof ApiError ? reset.error : null;
  return (
    <AuthLayout title="Choose a new password">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (form.password === form.confirm) reset.mutate();
        }}
        className="space-y-4"
      >
        <FormError error={reset.error && !error?.errors.length ? reset.error : null} />
        <PasswordFields
          label="New password"
          password={form.password}
          confirm={form.confirm}
          onPassword={(password) => setForm({ ...form, password })}
          onConfirm={(confirm) => setForm({ ...form, confirm })}
          error={error?.errors.map((x) => x.message).join(" ") || undefined}
        />
        <Button type="submit" className="w-full" loading={reset.isPending}>
          Set new password
        </Button>
      </form>
    </AuthLayout>
  );
}
