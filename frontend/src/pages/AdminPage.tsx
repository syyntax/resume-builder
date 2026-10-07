import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Mail, Shield, ShieldOff, Trash2, UserCheck, UserX } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useSearchParams } from "react-router";

import { api, errorMessage } from "../api/client";
import type { AuditEntry, Invite, Link as ResetLink, RegistrationMode, SystemSettings, User } from "../api/types";
import { meKey, useMe } from "../auth/auth";
import { Dialog } from "../components/Dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CopyField,
  PageHeader,
  Spinner,
  TextArea,
  TextField,
  cn,
} from "../components/ui";
import { formatDateTime, timeAgo } from "../lib/format";

const tabs = [
  { id: "users", label: "Users" },
  { id: "invites", label: "Invites" },
  { id: "settings", label: "Registration" },
  { id: "audit", label: "Audit log" },
] as const;
type TabId = (typeof tabs)[number]["id"];

// ---- users --------------------------------------------------------------------------------------------

type Pending = { kind: "reset"; user: User } | { kind: "delete"; user: User } | null;

function UsersTab() {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api<User[]>("GET", "/api/admin/users") });
  const [pending, setPending] = useState<Pending>(null);
  const [resetLink, setResetLink] = useState<ResetLink | null>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    void queryClient.invalidateQueries({ queryKey: meKey });
  };

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { role?: string; status?: string } }) =>
      api<User>("PATCH", `/api/admin/users/${id}`, { json: body }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>("DELETE", `/api/admin/users/${id}`),
    onSuccess: () => {
      setPending(null);
      refresh();
    },
  });
  const reset = useMutation({
    mutationFn: (id: string) => api<ResetLink>("POST", `/api/admin/users/${id}/reset-link`),
    onSuccess: setResetLink,
  });

  if (users.isPending) return <Spinner />;
  if (users.isError) return <Alert tone="error">{errorMessage(users.error)}</Alert>;

  return (
    <Card>
      <CardHeader title="Users" description="Admins manage accounts but can't see anyone's résumés." />
      {update.isError && <Alert tone="error" className="mx-5 mt-4">{errorMessage(update.error)}</Alert>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-xs text-slate-500 uppercase dark:border-slate-800">
            <tr>
              <th className="px-5 py-2 font-medium">User</th>
              <th className="px-3 py-2 font-medium">Role</th>
              <th className="px-3 py-2 font-medium">Last sign-in</th>
              <th className="px-5 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {users.data.map((u) => {
              const self = u.id === me?.user.id;
              const busy = update.isPending && update.variables?.id === u.id;
              return (
                <tr key={u.id} className={cn(u.status === "disabled" && "opacity-60")}>
                  <td className="px-5 py-3">
                    <p className="font-medium text-slate-900 dark:text-slate-100">
                      {u.displayName} {self && <Badge>You</Badge>}
                    </p>
                    <p className="text-slate-500">{u.email}</p>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1">
                      <Badge tone={u.role === "admin" ? "brand" : "neutral"}>{u.role === "admin" ? "Admin" : "User"}</Badge>
                      {u.status === "disabled" && <Badge tone="red">Disabled</Badge>}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-slate-500">{u.lastLoginAt ? timeAgo(u.lastLoginAt) : "Never"}</td>
                  <td className="px-5 py-3">
                    <div className="flex flex-wrap justify-end gap-1">
                      <Button variant="ghost" size="sm" disabled={busy} title={u.role === "admin" ? "Remove admin" : "Make admin"}
                        icon={u.role === "admin" ? <ShieldOff className="size-4" aria-hidden /> : <Shield className="size-4" aria-hidden />}
                        onClick={() => update.mutate({ id: u.id, body: { role: u.role === "admin" ? "user" : "admin" } })}>
                        <span className="sr-only sm:not-sr-only">{u.role === "admin" ? "Remove admin" : "Make admin"}</span>
                      </Button>
                      {!self && (
                        <Button variant="ghost" size="sm" disabled={busy} title={u.status === "active" ? "Disable" : "Enable"}
                          icon={u.status === "active" ? <UserX className="size-4" aria-hidden /> : <UserCheck className="size-4" aria-hidden />}
                          onClick={() => update.mutate({ id: u.id, body: { status: u.status === "active" ? "disabled" : "active" } })}>
                          <span className="sr-only sm:not-sr-only">{u.status === "active" ? "Disable" : "Enable"}</span>
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" title="Create a password reset link" icon={<KeyRound className="size-4" aria-hidden />}
                        onClick={() => { setResetLink(null); setPending({ kind: "reset", user: u }); reset.mutate(u.id); }}>
                        <span className="sr-only sm:not-sr-only">Reset link</span>
                      </Button>
                      {!self && (
                        <Button variant="ghost" size="sm" title="Delete" icon={<Trash2 className="size-4 text-red-600" aria-hidden />}
                          onClick={() => setPending({ kind: "delete", user: u })}>
                          <span className="sr-only">Delete</span>
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog open={pending?.kind === "reset"} title={`Password reset link for ${pending?.user.displayName ?? ""}`}
        description="Send this link to them privately. It works once and expires in 30 minutes. Using it signs them out everywhere."
        onClose={() => setPending(null)}>
        {reset.isPending && <Spinner />}
        {reset.isError && <Alert tone="error">{errorMessage(reset.error)}</Alert>}
        {resetLink && <CopyField label="Reset link" value={resetLink.url} />}
      </Dialog>
      <Dialog open={pending?.kind === "delete"} tone="danger" title={`Delete ${pending?.user.displayName ?? ""}?`} confirmLabel="Delete user"
        description="Their account and everything they own (master résumés, applications) are deleted permanently."
        busy={remove.isPending} onClose={() => { setPending(null); remove.reset(); }}
        onConfirm={() => pending && remove.mutate(pending.user.id)}>
        {remove.isError && <Alert tone="error">{errorMessage(remove.error)}</Alert>}
      </Dialog>
    </Card>
  );
}

// ---- invites ------------------------------------------------------------------------------------------

function InvitesTab() {
  const queryClient = useQueryClient();
  const invites = useQuery({ queryKey: ["admin", "invites"], queryFn: () => api<Invite[]>("GET", "/api/admin/invites") });
  const [email, setEmail] = useState("");
  const [created, setCreated] = useState<Invite | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["admin", "invites"] });
  const create = useMutation({
    mutationFn: () => api<Invite>("POST", "/api/admin/invites", { json: email.trim() ? { email: email.trim() } : {} }),
    onSuccess: (invite) => {
      setCreated(invite);
      setEmail("");
      refresh();
    },
  });
  const revoke = useMutation({ mutationFn: (id: string) => api<void>("DELETE", `/api/admin/invites/${id}`), onSuccess: refresh });

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Invite someone" description="Invite links work once and expire after 7 days. They work in every registration mode except closed." />
        <CardBody className="space-y-4">
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <TextField className="min-w-64 flex-1" label="Email (optional)" type="email" value={email}
              hint="If set, only this address can use the invite." onChange={(e) => setEmail(e.target.value)} />
            <Button type="submit" icon={<Mail className="size-4" aria-hidden />} loading={create.isPending}>Create invite link</Button>
          </form>
          {create.isError && <Alert tone="error">{errorMessage(create.error)}</Alert>}
          {created?.url && (
            <Alert tone="success" title="Invite created">
              <div className="mt-2"><CopyField label="Share this link" value={created.url} /></div>
              <p className="mt-2 text-xs">The link is shown only once. Without email configured, send it yourself.</p>
            </Alert>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Pending invites" />
        {invites.isPending ? (
          <CardBody><Spinner /></CardBody>
        ) : invites.data?.length ? (
          <ul className="divide-y divide-slate-200 dark:divide-slate-800">
            {invites.data.map((invite) => (
              <li key={invite.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
                <span className="font-medium text-slate-900 dark:text-slate-100">{invite.email ?? "Anyone with the link"}</span>
                <span className="text-slate-500">expires {timeAgo(invite.expiresAt)}</span>
                <Button variant="ghost" size="sm" loading={revoke.isPending && revoke.variables === invite.id} onClick={() => revoke.mutate(invite.id)}>
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <CardBody><p className="text-sm text-slate-500">No pending invites.</p></CardBody>
        )}
      </Card>
    </div>
  );
}

// ---- registration settings ---------------------------------------------------------------------------

const modes: { id: RegistrationMode; title: string; description: string }[] = [
  { id: "open", title: "Open", description: "Anyone who can reach the app can create an account. Good for a local, personal deployment." },
  { id: "invite", title: "Invite only", description: "People need an invite link from an admin." },
  { id: "closed", title: "Closed", description: "No new accounts, even with an invite." },
];

function SettingsForm({ settings }: { settings: SystemSettings }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<RegistrationMode>(settings.registrationMode);
  const [domains, setDomains] = useState(settings.registrationEmailDomains.join("\n"));
  const save = useMutation({
    mutationFn: () =>
      api<SystemSettings>("PUT", "/api/admin/settings", {
        json: { registrationMode: mode, registrationEmailDomains: domains.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean) },
      }),
    onSuccess: (value) => {
      queryClient.setQueryData(["admin", "settings"], value);
      void queryClient.invalidateQueries({ queryKey: meKey });
      void queryClient.invalidateQueries({ queryKey: ["registration"] });
    },
  });

  return (
    <Card>
      <CardHeader title="Registration" description="Who can create an account." />
      <CardBody>
        <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          {settings.openRegistrationExposed && (
            <Alert tone="warning" title="This app is reachable beyond localhost">
              With open registration and no domain list, anyone who finds it can sign up. New users still need their own API key before they can spend anything.
            </Alert>
          )}
          <fieldset className="grid gap-3 sm:grid-cols-3">
            <legend className="sr-only">Registration mode</legend>
            {modes.map((m) => (
              <label key={m.id} className={cn(
                "cursor-pointer rounded-lg border p-4 transition",
                mode === m.id ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500 dark:bg-brand-900/30" : "border-slate-200 hover:border-slate-300 dark:border-slate-700",
              )}>
                <input type="radio" name="mode" value={m.id} checked={mode === m.id} onChange={() => setMode(m.id)} className="sr-only" />
                <p className="font-medium text-slate-900 dark:text-slate-100">{m.title}</p>
                <p className="mt-1 text-sm text-slate-500">{m.description}</p>
              </label>
            ))}
          </fieldset>
          {mode === "open" && (
            <TextArea label="Allowed email domains (optional)" value={domains} rows={3} placeholder="example.com"
              hint="One per line. Leave empty to allow any domain. Invite links skip this check."
              onChange={(e) => setDomains(e.target.value)} />
          )}
          <div className="flex items-center gap-3">
            <Button type="submit" loading={save.isPending}>Save</Button>
            {save.isSuccess && <span className="text-sm text-emerald-700 dark:text-emerald-400">Saved.</span>}
            {save.isError && <span className="text-sm text-red-600">{errorMessage(save.error)}</span>}
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function SettingsTab() {
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: () => api<SystemSettings>("GET", "/api/admin/settings") });
  if (settings.isPending) return <Spinner />;
  if (settings.isError) return <Alert tone="error">{errorMessage(settings.error)}</Alert>;
  return <SettingsForm key={JSON.stringify(settings.data)} settings={settings.data} />;
}

// ---- audit log -----------------------------------------------------------------------------------------

function AuditTab() {
  const [filter, setFilter] = useState("");
  const [applied, setApplied] = useState("");
  const log = useInfiniteQuery({
    queryKey: ["admin", "audit", applied],
    initialPageParam: "",
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "50" });
      if (applied) params.set("event", applied);
      if (pageParam) params.set("before", pageParam);
      return api<AuditEntry[]>("GET", `/api/admin/audit-log?${params}`);
    },
    getNextPageParam: (last) => (last.length === 50 ? last[last.length - 1]?.createdAt : undefined),
  });
  const entries = log.data?.pages.flat() ?? [];

  return (
    <Card>
      <CardHeader title="Audit log" description="Security events only. Document content is never recorded." />
      <CardBody>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); setApplied(filter.trim()); }}>
          <TextField className="min-w-60" label="Event filter" placeholder="auth.login" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <Button type="submit" variant="secondary">Filter</Button>
        </form>
      </CardBody>
      {log.isPending ? (
        <CardBody><Spinner /></CardBody>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-y border-slate-200 text-xs text-slate-500 uppercase dark:border-slate-800">
              <tr>
                <th className="px-5 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Event</th>
                <th className="px-3 py-2 font-medium">Who</th>
                <th className="px-5 py-2 font-medium">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {entries.map((e) => (
                <tr key={e.id} className="align-top">
                  <td className="px-5 py-2 whitespace-nowrap text-slate-500" title={formatDateTime(e.createdAt)}>{timeAgo(e.createdAt)}</td>
                  <td className="px-3 py-2"><code className="text-xs">{e.event}</code></td>
                  <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
                    {e.actorEmail ?? "—"}
                    {e.targetEmail && e.targetEmail !== e.actorEmail && <span className="text-slate-500"> → {e.targetEmail}</span>}
                    {e.ip && <p className="text-xs text-slate-500">{e.ip}</p>}
                  </td>
                  <td className="px-5 py-2">
                    {Object.keys(e.details).length > 0 && (
                      <code className="block max-w-xs truncate text-xs text-slate-500" title={JSON.stringify(e.details)}>{JSON.stringify(e.details)}</code>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {entries.length === 0 && <CardBody><p className="text-sm text-slate-500">No events match.</p></CardBody>}
        </div>
      )}
      {log.hasNextPage && (
        <CardBody>
          <Button variant="secondary" size="sm" loading={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>Load older events</Button>
        </CardBody>
      )}
    </Card>
  );
}

// ---- page ----------------------------------------------------------------------------------------------

export function AdminPage() {
  const [params, setParams] = useSearchParams();
  const active = (tabs.find((t) => t.id === params.get("tab"))?.id ?? "users") as TabId;
  const panels: Record<TabId, ReactNode> = {
    users: <UsersTab />,
    invites: <InvitesTab />,
    settings: <SettingsTab />,
    audit: <AuditTab />,
  };
  return (
    <>
      <PageHeader title="Admin" description="Accounts, invites, registration and security events." />
      <div role="tablist" aria-label="Admin sections" className="mb-6 flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-800">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={active === t.id}
            onClick={() => setParams({ tab: t.id }, { replace: true })}
            className={cn(
              "-mb-px border-b-2 px-4 py-2 text-sm font-medium whitespace-nowrap",
              active === t.id
                ? "border-brand-600 text-brand-700 dark:border-brand-400 dark:text-brand-200"
                : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">{panels[active]}</div>
    </>
  );
}
