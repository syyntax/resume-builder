import { Briefcase, FileText, Home, LogOut, Menu, Shield, UserRound, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useMatches, useNavigate } from "react-router";

import { useMe, useSignOut } from "../auth/auth";
import { Alert, Badge, cn } from "../components/ui";
import { Logo } from "./Logo";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  soon?: boolean;
  end?: boolean;
}

function NavItems({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  return (
    <nav className="space-y-1" aria-label="Main">
      {items.map((item) =>
        item.soon ? (
          <span
            key={item.to}
            className="flex cursor-default items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-400 dark:text-slate-500"
            title="Coming in a later release"
          >
            {item.icon}
            <span className="flex-1">{item.label}</span>
            <Badge>Soon</Badge>
          </span>
        ) : (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-brand-50 text-brand-700 dark:bg-brand-900/50 dark:text-brand-100"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100",
              )
            }
          >
            {item.icon}
            {item.label}
          </NavLink>
        ),
      )}
    </nav>
  );
}

export function AppShell() {
  const { data: me } = useMe();
  const signOut = useSignOut();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  // Routes with `handle: { wide: true }` (side-by-side screens such as import review) use the full width.
  const wide = useMatches().some((match) => (match.handle as { wide?: boolean } | undefined)?.wide);

  useEffect(() => setMenuOpen(false), [location.pathname]);

  if (!me) return null;
  const isAdmin = me.user.role === "admin";
  const icon = "size-4 shrink-0";
  const items: NavItem[] = [
    { to: "/", label: "Home", icon: <Home className={icon} aria-hidden />, end: true },
    { to: "/masters", label: "Master résumés", icon: <FileText className={icon} aria-hidden /> },
    { to: "/applications", label: "Applications", icon: <Briefcase className={icon} aria-hidden /> },
    { to: "/account", label: "Account", icon: <UserRound className={icon} aria-hidden /> },
    ...(isAdmin ? [{ to: "/admin", label: "Admin", icon: <Shield className={icon} aria-hidden /> }] : []),
  ];

  const userCard = (
    <div className="border-t border-slate-200 pt-4 dark:border-slate-800">
      <div className="flex items-center gap-3 px-1">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700 dark:bg-brand-900 dark:text-brand-100">
          {me.user.displayName.slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{me.user.displayName}</p>
          <p className="truncate text-xs text-slate-500">{me.user.email}</p>
        </div>
        <button
          type="button"
          onClick={() => signOut.mutate(undefined, { onSettled: () => navigate("/login") })}
          className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          aria-label="Sign out"
          title="Sign out"
        >
          <LogOut className="size-4" aria-hidden />
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-dvh md:flex">
      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-6 border-r border-slate-200 bg-white px-4 py-5 md:flex dark:border-slate-800 dark:bg-slate-900">
        <Link to="/" className="px-2">
          <Logo />
        </Link>
        <div className="flex-1">
          <NavItems items={items} />
        </div>
        {userCard}
      </aside>

      {/* mobile top bar + drawer */}
      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur md:hidden dark:border-slate-800 dark:bg-slate-900/95">
        <Link to="/">
          <Logo />
        </Link>
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          className="rounded-md p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
        >
          {menuOpen ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
        </button>
      </header>
      {menuOpen && (
        <div className="space-y-4 border-b border-slate-200 bg-white px-4 py-4 md:hidden dark:border-slate-800 dark:bg-slate-900">
          <NavItems items={items} onNavigate={() => setMenuOpen(false)} />
          {userCard}
        </div>
      )}

      <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <div className={cn("mx-auto", wide ? "max-w-[96rem]" : "max-w-5xl")}>
          {me.notices.includes("open-registration-exposed") && (
            <Alert tone="warning" title="Anyone who can reach this app can create an account" className="mb-6">
              Registration is open and the app isn't running on localhost.{" "}
              <Link to="/admin?tab=settings" className="font-medium underline underline-offset-2">
                Switch to invite-only or limit sign-ups to your email domain
              </Link>
              .
            </Alert>
          )}
          <Outlet />
        </div>
      </main>
    </div>
  );
}
