import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";

import { ApiError, setUnauthorizedHandler } from "./api/client";
import { GuestOnly, RequireAdmin, RequireAuth, meKey } from "./auth/auth";
import { AppShell } from "./layouts/AppShell";
import { AccountPage } from "./pages/AccountPage";
import { AdminPage } from "./pages/AdminPage";
import { ApplicationsPage, NewApplicationPage } from "./pages/ApplicationsPages";
import { ForgotPasswordPage, LoginPage, RegisterPage, ResetPasswordPage, SetupPage, VerifyEmailPage } from "./pages/AuthPages";
import { HomePage } from "./pages/HomePage";
import { MasterDetailPage, MastersPage } from "./pages/MastersPages";
import { NotFoundPage } from "./pages/NotFoundPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
});

// A 401 anywhere means the session ended (expired, or revoked on another device): show sign-in. If sign-in is only
// incomplete (two-step verification became required), reload who's signed in: the app then asks for it.
setUnauthorizedHandler((reason) => {
  if (reason === "signed-out") queryClient.setQueryData(meKey, null);
  else void queryClient.invalidateQueries({ queryKey: meKey });
});

const router = createBrowserRouter([
  { path: "/setup", element: <SetupPage /> },
  {
    element: <GuestOnly />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
      { path: "/invite/:token", element: <RegisterPage /> },
      { path: "/forgot-password", element: <ForgotPasswordPage /> },
    ],
  },
  { path: "/reset-password/:token", element: <ResetPasswordPage /> },
  { path: "/verify-email/:token", element: <VerifyEmailPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "masters", element: <MastersPage /> },
          // The editors, import screens and application workspace bring in drag-and-drop, Monaco and PDF.js: load them on demand.
          { path: "masters/import", lazy: () => import("./pages/ImportPages").then((m) => ({ Component: m.ImportStartPage })) },
          { path: "masters/:id", element: <MasterDetailPage /> },
          { path: "masters/:id/edit", handle: { wide: true }, lazy: () => import("./pages/MasterEditPage").then((m) => ({ Component: m.MasterEditPage })) },
          { path: "imports/:id", handle: { wide: true }, lazy: () => import("./pages/ImportPages").then((m) => ({ Component: m.ImportReviewPage })) },
          { path: "applications", element: <ApplicationsPage /> },
          { path: "applications/new", element: <NewApplicationPage /> },
          { path: "applications/:id", handle: { wide: true }, lazy: () => import("./pages/ApplicationDetailPage").then((m) => ({ Component: m.ApplicationDetailPage })) },
          { path: "account", element: <AccountPage /> },
          { element: <RequireAdmin />, children: [{ path: "admin", element: <AdminPage /> }] },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
