import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Outlet, useLocation } from "react-router";

import { ApiError, api, setCsrfToken } from "../api/client";
import type { Me, RegistrationInfo } from "../api/types";
import { FullPageSpinner } from "../components/ui";
import { MfaChallengePage, MfaEnrollPage } from "../pages/MfaPages";
import { NotFoundPage } from "../pages/NotFoundPage";

export const meKey = ["me"] as const;
export const registrationKey = ["registration"] as const;

async function fetchMe(): Promise<Me | null> {
  try {
    const me = await api<Me>("GET", "/api/auth/me");
    setCsrfToken(me.csrfToken);
    return me;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw error;
  }
}

export function useMe() {
  return useQuery({ queryKey: meKey, queryFn: fetchMe, staleTime: 60_000, retry: false });
}

export function useRegistrationInfo() {
  return useQuery({
    queryKey: registrationKey,
    queryFn: () => api<RegistrationInfo>("GET", "/api/auth/registration"),
    staleTime: 30_000,
  });
}

/** Store a fresh session (after setup, sign-in, registration or a password change). */
export function useSetMe() {
  const queryClient = useQueryClient();
  return (me: Me | null) => {
    setCsrfToken(me?.csrfToken ?? null);
    queryClient.setQueryData(meKey, me);
  };
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("POST", "/api/auth/logout"),
    onSettled: () => {
      setCsrfToken(null);
      queryClient.clear();
      queryClient.setQueryData(meKey, null);
    },
  });
}

export function RequireAuth() {
  const { data: me, isPending } = useMe();
  const location = useLocation();
  if (isPending) return <FullPageSpinner />;
  if (!me) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  // Signing in isn't finished: a code from the authenticator app, or setting it up because it's required
  if (me.stage === "mfa") return <MfaChallengePage />;
  if (me.stage === "enroll") return <MfaEnrollPage />;
  return <Outlet />;
}

export function RequireAdmin() {
  const { data: me } = useMe();
  if (me?.user.role !== "admin") return <NotFoundPage />;
  return <Outlet />;
}

/** Sign-in pages: send signed-in users home and route to first-run setup when needed. */
export function GuestOnly({ allowDuringSetup = false }: { allowDuringSetup?: boolean }) {
  const { data: me, isPending } = useMe();
  const registration = useRegistrationInfo();
  if (isPending || registration.isPending) return <FullPageSpinner />;
  if (me) return <Navigate to="/" replace />;
  if (registration.data?.needsSetup && !allowDuringSetup) return <Navigate to="/setup" replace />;
  return <Outlet />;
}
