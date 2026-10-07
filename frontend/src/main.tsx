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
import { LoginPage, RegisterPage, ResetPasswordPage, SetupPage } from "./pages/AuthPages";
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

// A 401 anywhere means the session ended (expired, or revoked on another device): show sign-in.
setUnauthorizedHandler(() => queryClient.setQueryData(meKey, null));

const router = createBrowserRouter([
  { path: "/setup", element: <SetupPage /> },
  {
    element: <GuestOnly />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
      { path: "/invite/:token", element: <RegisterPage /> },
    ],
  },
  { path: "/reset-password/:token", element: <ResetPasswordPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "masters", element: <MastersPage /> },
          { path: "masters/:id", element: <MasterDetailPage /> },
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
