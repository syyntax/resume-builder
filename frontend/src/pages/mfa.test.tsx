import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { meKey } from "../auth/auth";
import { RecoveryCodeNotice } from "../components/AccountSecurity";
import { MfaSetup } from "../components/MfaSetup";
import { MfaChallengePage } from "./MfaPages";

const me = { user: { id: "usr_1", email: "jo@example.com", displayName: "Jo", role: "user", status: "active", createdAt: "", mfaEnabled: true },
  csrfToken: "t", notices: [], stage: "active" };

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function wrap(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>;
}

afterEach(() => vi.unstubAllGlobals());

describe("two-step verification", () => {
  it("finishes signing in with a code, or a recovery code", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { code: string };
      sent.push(body);
      return body.code === "123456" ? json({ detail: "That code didn't work." }, 401) : json(me);
    }));
    const client = new QueryClient();
    const user = userEvent.setup();
    render(<MfaChallengePage />, { wrapper: wrap(client) });
    await user.type(screen.getByLabelText("Code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("That code didn't work.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /recovery code/ }));
    await user.type(screen.getByLabelText("Recovery code"), "abcd-efgh-jk");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    await vi.waitFor(() => expect(client.getQueryData(meKey)).toEqual(me));
    expect(sent).toEqual([{ code: "123456" }, { code: "abcd-efgh-jk" }]);
  });

  it("says how many recovery codes are left after using one, until dismissed", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ enabled: true, recoveryCodesLeft: 9 })));
    const client = new QueryClient();
    client.setQueryData(meKey, { ...me, notices: ["recovery-code-used"] });
    const user = userEvent.setup();
    render(<RecoveryCodeNotice />, { wrapper: wrap(client) });
    expect(await screen.findByText(/You have 9 left/)).toBeInTheDocument();
    act(() => client.setQueryData(meKey, me));  // fetched again: the notice only came with that sign-in
    expect(screen.getByText("You signed in with a recovery code")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("You signed in with a recovery code")).not.toBeInTheDocument();
  });

  it("is set up by scanning a code and confirming it", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${url} ${String(init?.body)}`);
      if (url.endsWith("/setup")) return json({ secret: "ABCDEFGHIJKLMNOP", otpauthUri: "otpauth://totp/x", qrSvg: "<svg xmlns='http://www.w3.org/2000/svg'/>" });
      return json({ recoveryCodes: ["aaaa-bbbb-cc"], me });
    }));
    const onEnabled = vi.fn();
    const user = userEvent.setup();
    render(<MfaSetup needsPassword onEnabled={onEnabled} />, { wrapper: wrap(new QueryClient()) });
    await user.type(screen.getByLabelText("Your password"), "my password");
    await user.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByAltText("QR code for your authenticator app")).toHaveAttribute("src", expect.stringMatching(/^data:image\/svg\+xml/));
    expect(screen.getByText("ABCD EFGH IJKL MNOP")).toBeInTheDocument();  // the key, grouped for typing
    await user.type(screen.getByLabelText("Code"), "654321");
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    await vi.waitFor(() => expect(onEnabled).toHaveBeenCalledWith(me, ["aaaa-bbbb-cc"]));
    expect(calls).toEqual(['/api/auth/mfa/setup {"password":"my password"}', '/api/auth/mfa/enable {"code":"654321"}']);
  });
});
