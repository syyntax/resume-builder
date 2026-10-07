import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, LogOut, Monitor, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router";

import { ApiError, api, errorMessage, setCsrfToken } from "../api/client";
import type { Me, Session, User } from "../api/types";
import { meKey, useMe, useSetMe } from "../auth/auth";
import { Dialog } from "../components/Dialog";
import { PasswordFields } from "../components/PasswordFields";
import { Alert, Badge, Button, Card, CardBody, CardHeader, PageHeader, Spinner, TextField, linkButtonClass } from "../components/ui";
import { describeUserAgent, timeAgo } from "../lib/format";

function ProfileCard({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(user.displayName);
  const [email, setEmail] = useState(user.email);
  const [password, setPassword] = useState("");
  const emailChanged = email.trim().toLowerCase() !== user.email;

  const save = useMutation({
    mutationFn: () =>
      api<User>("PATCH", "/api/account/profile", {
        json: { displayName: name, ...(emailChanged ? { email, currentPassword: password } : {}) },
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData<Me | null>(meKey, (me) => (me ? { ...me, user: updated } : me));
      setPassword("");
    },
  });
  const error = save.error instanceof ApiError ? save.error : null;

  return (
    <Card>
      <CardHeader title="Profile" />
      <CardBody>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <TextField label="Name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} error={error?.fieldError("email")} />
          {emailChanged && (
            <TextField className="sm:col-span-2" label="Current password" type="password" required autoComplete="current-password"
              hint="Required to change your email." value={password} onChange={(e) => setPassword(e.target.value)}
              error={error?.fieldError("currentPassword") ? "Incorrect password." : undefined} />
          )}
          <div className="flex items-center gap-3 sm:col-span-2">
            <Button type="submit" loading={save.isPending}>Save profile</Button>
            {save.isSuccess && <span className="text-sm text-emerald-700 dark:text-emerald-400">Saved.</span>}
            {save.isError && !error?.errors.length && <span className="text-sm text-red-600">{errorMessage(save.error)}</span>}
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function PasswordCard() {
  const setMe = useSetMe();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ current: "", password: "", confirm: "" });
  const change = useMutation({
    mutationFn: () => api<Me>("POST", "/api/auth/password/change", { json: { currentPassword: form.current, newPassword: form.password } }),
    onSuccess: (me) => {
      setMe(me);
      setForm({ current: "", password: "", confirm: "" });
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
  const error = change.error instanceof ApiError ? change.error : null;
  return (
    <Card>
      <CardHeader title="Password" description="Changing your password signs you out on every other device." />
      <CardBody>
        <form
          className="max-w-md space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (form.password === form.confirm) change.mutate();
          }}
        >
          <TextField label="Current password" type="password" required autoComplete="current-password" value={form.current}
            onChange={(e) => setForm({ ...form, current: e.target.value })} error={error?.fieldError("currentPassword") ? "Incorrect password." : undefined} />
          <PasswordFields label="New password" password={form.password} confirm={form.confirm}
            onPassword={(password) => setForm({ ...form, password })} onConfirm={(confirm) => setForm({ ...form, confirm })}
            error={error?.errors.filter((x) => x.field === "newPassword").map((x) => x.message).join(" ") || undefined} />
          <div className="flex items-center gap-3">
            <Button type="submit" loading={change.isPending}>Change password</Button>
            {change.isSuccess && <span className="text-sm text-emerald-700 dark:text-emerald-400">Password changed.</span>}
            {change.isError && !error?.errors.length && <span className="text-sm text-red-600">{errorMessage(change.error)}</span>}
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function SessionsCard() {
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api<Session[]>("GET", "/api/auth/sessions") });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["sessions"] });
  const revoke = useMutation({ mutationFn: (id: string) => api<void>("DELETE", `/api/auth/sessions/${id}`), onSuccess: refresh });
  const revokeOthers = useMutation({ mutationFn: () => api<void>("DELETE", "/api/auth/sessions"), onSuccess: refresh });
  const others = (sessions.data ?? []).filter((s) => !s.current).length;

  return (
    <Card>
      <CardHeader
        title="Where you're signed in"
        actions={others > 0 && (
          <Button variant="secondary" size="sm" icon={<LogOut className="size-4" aria-hidden />} loading={revokeOthers.isPending}
            onClick={() => revokeOthers.mutate()}>
            Sign out other sessions
          </Button>
        )}
      />
      {sessions.isPending ? (
        <CardBody><Spinner /></CardBody>
      ) : (
        <ul className="divide-y divide-slate-200 dark:divide-slate-800">
          {sessions.data?.map((s) => (
            <li key={s.id} className="flex items-center gap-4 px-5 py-3 text-sm">
              <Monitor className="size-5 shrink-0 text-slate-400" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-slate-900 dark:text-slate-100">
                  {describeUserAgent(s.userAgent)} {s.current && <Badge tone="green">This device</Badge>}
                </p>
                <p className="text-slate-500">
                  {s.ip ?? "Unknown IP"} · active {timeAgo(s.lastSeenAt)} · signed in {timeAgo(s.createdAt)}
                </p>
              </div>
              {!s.current && (
                <Button variant="ghost" size="sm" loading={revoke.isPending && revoke.variables === s.id} onClick={() => revoke.mutate(s.id)}>
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function DataCard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const remove = useMutation({
    mutationFn: () => api<void>("DELETE", "/api/account", { json: { password } }),
    onSuccess: () => {
      setCsrfToken(null);
      queryClient.clear();
      queryClient.setQueryData(meKey, null);
      navigate("/login", { replace: true });
    },
  });
  return (
    <Card>
      <CardHeader title="Your data" />
      <CardBody className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-medium text-slate-900 dark:text-slate-100">Export everything</p>
            <p className="text-sm text-slate-500">A ZIP of your profile and every master résumé version.</p>
          </div>
          <a href="/api/account/export" className={linkButtonClass("secondary", "sm")}>
            <Download className="size-4" aria-hidden /> Download export
          </a>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-5 dark:border-slate-800">
          <div>
            <p className="font-medium text-red-700 dark:text-red-400">Delete account</p>
            <p className="text-sm text-slate-500">Permanently deletes your account and everything in it.</p>
          </div>
          <Button variant="danger" size="sm" icon={<Trash2 className="size-4" aria-hidden />} onClick={() => setOpen(true)}>
            Delete account
          </Button>
        </div>
      </CardBody>
      <Dialog open={open} tone="danger" title="Delete your account?" confirmLabel="Delete my account" busy={remove.isPending}
        confirmDisabled={!password} onClose={() => { setOpen(false); setPassword(""); remove.reset(); }} onConfirm={() => remove.mutate()}
        description="This deletes your account, master résumés and applications. It can't be undone.">
        <TextField label="Password" type="password" autoComplete="current-password" value={password} autoFocus
          onChange={(e) => setPassword(e.target.value)} />
        {remove.isError && <Alert tone="error">{errorMessage(remove.error)}</Alert>}
      </Dialog>
    </Card>
  );
}

export function AccountPage() {
  const { data: me } = useMe();
  if (!me) return null;
  return (
    <>
      <PageHeader title="Account" description="Your profile, security and data." />
      <div className="space-y-6">
        <ProfileCard user={me.user} />
        <PasswordCard />
        <SessionsCard />
        <DataCard />
      </div>
    </>
  );
}
