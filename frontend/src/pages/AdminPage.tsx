import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleDollarSign, KeyRound, Mail, PlugZap, Shield, ShieldCheck, ShieldOff, Smartphone, Trash2, UserCheck, UserX } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useSearchParams } from "react-router";

import { api, errorMessage } from "../api/client";
import type {
  AdminAiSettings, AdminUser, AuditEntry, Invite, Link as ResetLink, RegistrationMode, SystemSettings, Theme, UserUsage,
} from "../api/types";
import { meKey, useMe } from "../auth/auth";
import { Dialog } from "../components/Dialog";
import { DesignPanel } from "../components/design";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  CopyField,
  PageHeader,
  Spinner,
  TableScroll,
  TextArea,
  TextField,
  cn,
} from "../components/ui";
import { formatDateTime, formatUsd, modelLabel, monthLabel, recentMonths, timeAgo } from "../lib/format";

const tabs = [
  { id: "users", label: "Users" },
  { id: "invites", label: "Invites" },
  { id: "settings", label: "Settings" },
  { id: "ai", label: "AI" },
  { id: "usage", label: "Usage" },
  { id: "audit", label: "Audit log" },
] as const;
type TabId = (typeof tabs)[number]["id"];

// ---- users --------------------------------------------------------------------------------------------

type Pending = { kind: "reset" | "delete" | "cap" | "mfa"; user: AdminUser } | null;

function UsersTab() {
  const { data: me } = useMe();
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api<AdminUser[]>("GET", "/api/admin/users") });
  const [pending, setPending] = useState<Pending>(null);
  const [cap, setCap] = useState("");
  const [resetLink, setResetLink] = useState<ResetLink | null>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    void queryClient.invalidateQueries({ queryKey: meKey });
  };

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api<AdminUser>("PATCH", `/api/admin/users/${id}`, { json: body }),
    onSuccess: () => {
      refresh();
      if (pending?.kind === "cap") setPending(null);
    },
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
  const resetMfa = useMutation({
    mutationFn: (id: string) => api<AdminUser>("POST", `/api/admin/users/${id}/mfa-reset`),
    onSuccess: () => { setPending(null); refresh(); },
  });

  if (users.isPending) return <Spinner />;
  if (users.isError) return <Alert tone="error">{errorMessage(users.error)}</Alert>;

  return (
    <Card>
      <CardHeader title="Users" description="Admins manage accounts but can't see anyone's résumés." />
      {update.isError && <Alert tone="error" className="mx-5 mt-4">{errorMessage(update.error)}</Alert>}
      <TableScroll label="Users">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-xs text-slate-500 dark:text-slate-400 uppercase dark:border-slate-800">
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
                    <p className="text-slate-500 dark:text-slate-400">{u.email}</p>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1">
                      <Badge tone={u.role === "admin" ? "brand" : "neutral"}>{u.role === "admin" ? "Admin" : "User"}</Badge>
                      {u.status === "disabled" && <Badge tone="red">Disabled</Badge>}
                      {u.hasApiKey && <Badge tone="green">Key on file</Badge>}
                      {u.mfaEnabled && <Badge tone="green"><ShieldCheck className="mr-1 size-3" aria-hidden />Two-step</Badge>}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-slate-500 dark:text-slate-400">{u.lastLoginAt ? timeAgo(u.lastLoginAt) : "Never"}</td>
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
                      <Button variant="ghost" size="sm" title="Shared-key allowance" icon={<CircleDollarSign className="size-4" aria-hidden />}
                        onClick={() => { setCap(u.sharedCapUsd === null ? "" : String(u.sharedCapUsd)); setPending({ kind: "cap", user: u }); }}>
                        <span className="sr-only">Shared-key allowance</span>
                      </Button>
                      <Button variant="ghost" size="sm" title="Create a password reset link" icon={<KeyRound className="size-4" aria-hidden />}
                        onClick={() => { setResetLink(null); setPending({ kind: "reset", user: u }); reset.mutate(u.id); }}>
                        <span className="sr-only sm:not-sr-only">Reset link</span>
                      </Button>
                      {u.mfaEnabled && !self && (
                        <Button variant="ghost" size="sm" title="Reset two-step verification" icon={<Smartphone className="size-4" aria-hidden />}
                          onClick={() => setPending({ kind: "mfa", user: u })}>
                          <span className="sr-only">Reset two-step verification</span>
                        </Button>
                      )}
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
      </TableScroll>

      <Dialog open={pending?.kind === "reset"} title={`Password reset link for ${pending?.user.displayName ?? ""}`}
        description="Send this link to them privately. It works once and expires in 30 minutes. Using it signs them out everywhere."
        onClose={() => setPending(null)}>
        {reset.isPending && <Spinner />}
        {reset.isError && <Alert tone="error">{errorMessage(reset.error)}</Alert>}
        {resetLink && <CopyField label="Reset link" value={resetLink.url} />}
      </Dialog>
      <Dialog open={pending?.kind === "cap"} title={`Shared-key allowance for ${pending?.user.displayName ?? ""}`}
        description="Monthly limit on what they can spend through the shared key (if you allow it). Their own key has its own cap, which they set."
        confirmLabel="Save" busy={update.isPending} onClose={() => setPending(null)}
        onConfirm={() => pending && update.mutate({ id: pending.user.id, body: cap.trim() === "" ? { resetSharedCap: true } : { sharedCapUsd: Number(cap) } })}>
        <TextField label="Monthly allowance (USD)" type="number" min={0} step="1" value={cap} onChange={(e) => setCap(e.target.value)}
          hint="Leave empty for the default. 0 means unlimited." />
      </Dialog>
      <Dialog open={pending?.kind === "mfa"} tone="danger" title={`Reset two-step verification for ${pending?.user.displayName ?? ""}?`}
        confirmLabel="Reset" busy={resetMfa.isPending} onClose={() => { setPending(null); resetMfa.reset(); }}
        description="For someone who lost their phone and recovery codes. It's turned off and they're signed out everywhere. Check it's really them first: anyone with their password can then sign in."
        onConfirm={() => pending && resetMfa.mutate(pending.user.id)}>
        {resetMfa.isError && <Alert tone="error">{errorMessage(resetMfa.error)}</Alert>}
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
              <p className="mt-2 text-xs">{created.emailed ? `We also emailed it to ${created.email}.` : "The link is shown only once. Send it yourself."}</p>
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
                <span className="text-slate-500 dark:text-slate-400">expires {timeAgo(invite.expiresAt)}</span>
                <Button variant="ghost" size="sm" loading={revoke.isPending && revoke.variables === invite.id} onClick={() => revoke.mutate(invite.id)}>
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <CardBody><p className="text-sm text-slate-500 dark:text-slate-400">No pending invites.</p></CardBody>
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

const mfaPolicies: { id: SystemSettings["requireMfa"]; title: string; description: string }[] = [
  { id: "none", title: "Optional", description: "People can turn it on for themselves." },
  { id: "admins", title: "Required for admins", description: "Admins set it up at their next sign-in." },
  { id: "all", title: "Required for everyone", description: "Everyone sets it up at their next sign-in." },
];

function SettingsForm({ settings }: { settings: SystemSettings }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<RegistrationMode>(settings.registrationMode);
  const [domains, setDomains] = useState(settings.registrationEmailDomains.join("\n"));
  const [mfa, setMfa] = useState(settings.requireMfa);
  const [design, setDesign] = useState<{ template: string; theme: Theme }>(settings.defaultDesign);
  const save = useMutation({
    mutationFn: () =>
      api<SystemSettings>("PUT", "/api/admin/settings", {
        json: { registrationMode: mode, registrationEmailDomains: domains.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean),
          requireMfa: mfa, defaultDesign: design },
      }),
    onSuccess: (value) => {
      setMode(value.registrationMode);  // as stored (domains normalized)
      setDomains(value.registrationEmailDomains.join("\n"));
      setMfa(value.requireMfa);
      setDesign(value.defaultDesign);
      queryClient.setQueryData(["admin", "settings"], value);
      void queryClient.invalidateQueries({ queryKey: meKey });
      void queryClient.invalidateQueries({ queryKey: ["registration"] });
    },
  });

  return (
    <Card>
      <CardHeader title="Settings" description="Who can create an account, how they sign in, and the look of new applications." />
      <CardBody>
        <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Registration</h3>
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
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{m.description}</p>
              </label>
            ))}
          </fieldset>
          {mode === "open" && (
            <TextArea label="Allowed email domains (optional)" value={domains} rows={3} placeholder="example.com"
              hint="One per line. Leave empty to allow any domain. Invite links skip this check."
              onChange={(e) => setDomains(e.target.value)} />
          )}
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {settings.emailEnabled
              ? "Email is set up: people can reset their own password, invites are emailed, and open sign-ups confirm their address."
              : "Email isn't set up, so you share invite and password reset links yourself. To change that, set SMTP_HOST and SMTP_FROM in the server's env file."}
          </p>
          <fieldset className="space-y-3 border-t border-slate-200 pt-5 dark:border-slate-800">
            <legend className="text-sm font-semibold text-slate-900 dark:text-slate-100">Two-step verification</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              {mfaPolicies.map((p) => (
                <label key={p.id} className={cn("cursor-pointer rounded-lg border p-4 transition",
                  mfa === p.id ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500 dark:bg-brand-900/30" : "border-slate-200 hover:border-slate-300 dark:border-slate-700")}>
                  <input type="radio" name="mfa" value={p.id} checked={mfa === p.id} onChange={() => setMfa(p.id)} className="sr-only" />
                  <p className="font-medium text-slate-900 dark:text-slate-100">{p.title}</p>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{p.description}</p>
                </label>
              ))}
            </div>
            {mfa !== "none" && settings.requireMfa === "none" && (
              <p className="text-xs text-slate-500 dark:text-slate-400">If you haven't set it up yourself, you'll be asked to right after saving.</p>
            )}
          </fieldset>
          <div className="space-y-3 border-t border-slate-200 pt-5 dark:border-slate-800">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Default design</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">New applications start with this template and theme, unless someone picked their own in Account → Preferences.</p>
            <DesignPanel template={design.template} theme={design.theme} onChange={(template, theme) => setDesign({ template, theme })} />
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" loading={save.isPending}>Save</Button>
            {save.isSuccess && <span className="text-sm text-emerald-700 dark:text-emerald-400">Saved.</span>}
            {save.isError && <span className="text-sm text-red-600 dark:text-red-400">{errorMessage(save.error)}</span>}
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
  return <SettingsForm settings={settings.data} />;
}

// ---- AI settings ---------------------------------------------------------------------------------------

const STAGES = [["analyze", "Analyzing postings"], ["tailor", "Tailoring"], ["letter", "Cover letters"], ["import", "Importing résumés"],
  ["refine", "Refine suggestions"], ["audit", "Claim audit"], ["condense", "Condensing letters"]] as const;

function AiForm({ settings }: { settings: AdminAiSettings }) {
  const queryClient = useQueryClient();
  const [allowShared, setAllowShared] = useState(settings.allowSharedKey);
  const [allowed, setAllowed] = useState<string[]>(settings.allowedModels);
  const [fallbackDefault, setDefault] = useState(settings.defaultModel);
  const [effort, setEffort] = useState(settings.effort);
  const [claimAudit, setClaimAudit] = useState(settings.claimAudit);
  const save = useMutation({
    mutationFn: () => api<AdminAiSettings>("PUT", "/api/admin/ai-settings", {
      json: { allowSharedKey: settings.sharedKeyConfigured ? allowShared : undefined, allowedModels: allowed, defaultModel: fallbackDefault,
        effort, claimAudit },
    }),
    onSuccess: (value) => {
      setAllowShared(value.allowSharedKey);  // as stored
      setAllowed(value.allowedModels);
      setDefault(value.defaultModel);
      setEffort(value.effort);
      setClaimAudit(value.claimAudit);
      queryClient.setQueryData(["admin", "ai"], value);
    },
  });
  const test = useMutation({ mutationFn: () => api<void>("POST", "/api/admin/ai-settings/test-connection") });
  const toggle = (model: string) =>
    setAllowed((current) => (current.includes(model) ? current.filter((m) => m !== model) : [...current, model]));

  return (
    <Card>
      <CardHeader title="AI" description="Models people can use, and the optional shared key." />
      <CardBody>
        <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <fieldset>
            <legend className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">Allowed models</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {settings.knownModels.map((m) => (
                <label key={m} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
                  <span className="flex items-center gap-2">
                    <input type="checkbox" checked={allowed.includes(m)} onChange={() => toggle(m)} className="size-4 rounded border-slate-300" />
                    {modelLabel(m)}
                  </span>
                  {allowed.includes(m) && (
                    <span className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                      <input type="radio" name="default-model" checked={fallbackDefault === m} onChange={() => setDefault(m)} aria-label={`Make ${modelLabel(m)} the default`} />
                      default
                    </span>
                  )}
                </label>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">People pick from these in Account → AI. The default is used when they haven't chosen.</p>
          </fieldset>
          <fieldset className="space-y-3 border-t border-slate-200 pt-5 dark:border-slate-800">
            <legend className="text-sm font-medium text-slate-700 dark:text-slate-300">Effort per step</legend>
            <p className="text-xs text-slate-500 dark:text-slate-400">More effort thinks longer: usually better, slower and costlier. The defaults suit most uses.</p>
            <div className="grid gap-3 sm:grid-cols-4">
              {STAGES.map(([key, label]) => (
                <label key={key} className="text-sm">
                  <span className="mb-1 block text-xs text-slate-600 dark:text-slate-400">{label}</span>
                  <select className="block w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
                    value={effort[key]} onChange={(e) => setEffort({ ...effort, [key]: e.target.value as typeof effort[typeof key] })}>
                    {["low", "medium", "high", "xhigh", "max"].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <Checkbox label="Check every claim against its sources after each generation (claim audit)" checked={claimAudit}
              onChange={(e) => setClaimAudit(e.target.checked)} />
            <p className="text-xs text-slate-500 dark:text-slate-400">A second, inexpensive pass that flags anything overstating what someone's master résumé says. People can still run it themselves.</p>
          </fieldset>
          <div className="space-y-2 border-t border-slate-200 pt-5 dark:border-slate-800">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Shared key</p>
            {settings.sharedKeyConfigured ? (
              <>
                <Checkbox label="Let people without their own key use the shared key" checked={allowShared} onChange={(e) => setAllowShared(e.target.checked)} />
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Each person's shared-key spending is capped at {formatUsd(settings.defaultCapUsd)} a month by default; change it per person on the Users tab.
                </p>
                <Button variant="secondary" size="sm" icon={<PlugZap className="size-4" aria-hidden />} loading={test.isPending} onClick={() => test.mutate()}>Test shared key</Button>
                {test.isSuccess && <p className="text-sm text-emerald-700 dark:text-emerald-400">The shared key works.</p>}
                {test.isError && <p className="text-sm text-red-600 dark:text-red-400">{errorMessage(test.error)}</p>}
              </>
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                None configured. To offer one, set <code className="rounded bg-slate-100 px-1 text-slate-700 dark:bg-slate-800 dark:text-slate-300">ANTHROPIC_API_KEY</code> in the server's env file and restart.
                Until then, everyone uses their own key.
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" loading={save.isPending} disabled={allowed.length === 0 || !allowed.includes(fallbackDefault)}>Save</Button>
            {save.isSuccess && <span className="text-sm text-emerald-700 dark:text-emerald-400">Saved.</span>}
            {save.isError && <span className="text-sm text-red-600 dark:text-red-400">{errorMessage(save.error)}</span>}
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

function AiTab() {
  const settings = useQuery({ queryKey: ["admin", "ai"], queryFn: () => api<AdminAiSettings>("GET", "/api/admin/ai-settings") });
  if (settings.isPending) return <Spinner />;
  if (settings.isError) return <Alert tone="error">{errorMessage(settings.error)}</Alert>;
  return <AiForm settings={settings.data} />;
}

const selectClass = "rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

function UsageTab() {
  const months = recentMonths();
  const [month, setMonth] = useState(months[0]!);
  const rows = useQuery({ queryKey: ["admin", "usage", month], queryFn: () => api<UserUsage[]>("GET", `/api/admin/usage?month=${month}`) });
  if (rows.isPending) return <Spinner />;
  if (rows.isError) return <Alert tone="error">{errorMessage(rows.error)}</Alert>;
  return (
    <Card>
      <CardHeader title="Usage" description="Estimated AI spending per person. Totals only; nobody's documents are visible here."
        actions={
          <select aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)} className={selectClass}>
            {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </select>
        } />
      <TableScroll label={`Usage in ${monthLabel(month)}`}>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-xs text-slate-500 dark:text-slate-400 uppercase dark:border-slate-800">
            <tr>
              <th className="px-5 py-2 font-medium">User</th>
              <th className="px-3 py-2 text-right font-medium">Own key</th>
              <th className="px-3 py-2 text-right font-medium">Shared key</th>
              <th className="px-3 py-2 text-right font-medium">Applications</th>
              <th className="px-3 py-2 text-right font-medium">Imports</th>
              <th className="px-5 py-2 text-right font-medium">AI calls</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {rows.data.map((r) => (
              <tr key={r.userId}>
                <td className="px-5 py-3">
                  <p className="font-medium text-slate-900 dark:text-slate-100">{r.displayName} {r.hasApiKey && <Badge tone="green">Key</Badge>}</p>
                  <p className="text-slate-500 dark:text-slate-400">{r.email}</p>
                </td>
                <td className="px-3 py-3 text-right tabular-nums">{formatUsd(r.ownSpendUsd)}</td>
                <td className="px-3 py-3 text-right tabular-nums">{formatUsd(r.sharedSpendUsd)}</td>
                <td className="px-3 py-3 text-right tabular-nums">{r.applications}</td>
                <td className="px-3 py-3 text-right tabular-nums">{r.imports}</td>
                <td className="px-5 py-3 text-right tabular-nums">{r.calls}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </Card>
  );
}

// ---- audit log -----------------------------------------------------------------------------------------

type AuditFilters = { event: string; userId: string; since: string; until: string };
const NO_FILTERS: AuditFilters = { event: "", userId: "", since: "", until: "" };

function AuditTab() {
  const [filters, setFilters] = useState<AuditFilters>(NO_FILTERS);
  const [applied, setApplied] = useState<AuditFilters>(NO_FILTERS);
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api<AdminUser[]>("GET", "/api/admin/users") });
  const set = (key: keyof AuditFilters) => (e: { target: { value: string } }) => setFilters((f) => ({ ...f, [key]: e.target.value }));
  const log = useInfiniteQuery({
    queryKey: ["admin", "audit", applied],
    initialPageParam: "",
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "50" });
      for (const [key, value] of Object.entries({ ...applied, event: applied.event.trim() })) if (value) params.set(key, value);
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
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); setApplied(filters); }}>
          <TextField className="min-w-48" label="Event" placeholder="auth.login" value={filters.event} onChange={set("event")} />
          <label className="text-sm">
            <span className="mb-1.5 block font-medium text-slate-700 dark:text-slate-300">User</span>
            <select value={filters.userId} onChange={set("userId")} className={cn(selectClass, "py-2")}>
              <option value="">Anyone</option>
              {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
            </select>
          </label>
          <TextField label="From" type="date" value={filters.since} onChange={set("since")} />
          <TextField label="To" type="date" value={filters.until} onChange={set("until")} />
          <Button type="submit" variant="secondary">Filter</Button>
          {JSON.stringify(applied) !== JSON.stringify(NO_FILTERS) && (
            <Button variant="ghost" onClick={() => { setFilters(NO_FILTERS); setApplied(NO_FILTERS); }}>Clear</Button>
          )}
        </form>
      </CardBody>
      {log.isPending ? (
        <CardBody><Spinner /></CardBody>
      ) : (
        <TableScroll label="Audit log">
          <table className="w-full text-left text-sm">
            <thead className="border-y border-slate-200 text-xs text-slate-500 dark:text-slate-400 uppercase dark:border-slate-800">
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
                  <td className="px-5 py-2 whitespace-nowrap text-slate-500 dark:text-slate-400" title={formatDateTime(e.createdAt)}>{timeAgo(e.createdAt)}</td>
                  <td className="px-3 py-2"><code className="text-xs">{e.event}</code></td>
                  <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
                    {e.actorEmail ?? "—"}
                    {e.targetEmail && e.targetEmail !== e.actorEmail && <span className="text-slate-500 dark:text-slate-400"> → {e.targetEmail}</span>}
                    {e.ip && <p className="text-xs text-slate-500 dark:text-slate-400">{e.ip}</p>}
                  </td>
                  <td className="px-5 py-2">
                    {Object.keys(e.details).length > 0 && (
                      <code className="block max-w-xs truncate text-xs text-slate-500 dark:text-slate-400" title={JSON.stringify(e.details)}>{JSON.stringify(e.details)}</code>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {entries.length === 0 && <CardBody><p className="text-sm text-slate-500 dark:text-slate-400">No events match.</p></CardBody>}
        </TableScroll>
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
    ai: <AiTab />,
    usage: <UsageTab />,
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
                : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200",
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
