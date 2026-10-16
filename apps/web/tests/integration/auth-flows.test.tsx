import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { type ReactElement, useEffect } from "react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { useChallengeStore } from "@/features/auth/challenge-store";
import { LoginForm } from "@/features/auth/components/login-form";
import { RegisterForm } from "@/features/auth/components/register-form";
import { ResetPasswordForm } from "@/features/auth/components/reset-password-form";
import { SecuritySettings } from "@/features/auth/components/security-settings";
import { VerifyForm } from "@/features/auth/components/verify-form";
import { authKeys } from "@/features/auth/query-keys";
import { apiClient } from "@/lib/api/client";

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  query: "next=%2Fsettings%2Fsecurity",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  useSearchParams: () => new URLSearchParams(navigation.query),
}));
vi.mock("@/lib/auth/broadcast", () => ({ broadcastAuth: vi.fn() }));
vi.mock("@/components/shared/turnstile-field", () => ({
  TurnstileField: ({
    onToken,
    resetKey,
  }: {
    onToken: (value: string) => void;
    resetKey: number;
  }) => {
    useEffect(() => {
      onToken("test-token");
    }, [onToken, resetKey]);
    return null;
  },
}));

const api = `${window.location.origin}/v1/auth`;
const originalBaseURL = apiClient.defaults.baseURL;
const user = {
  id: "0199aabb-1111-7111-8111-111111111111",
  name: "Asha",
  roles: ["user"],
  permissions: [],
  status: "active",
  contacts: [{ destination: "a***@example.com", kind: "email", primary: true, verified: true }],
  hasPassword: true,
  linkedProviders: ["google"],
};
const challenge = {
  channel: "email",
  destination: "a***@example.com",
  resendAfter: 60,
  expiresIn: 300,
};
const server = setupServer();
let client: QueryClient;
const mount = (element: ReactElement) =>
  render(<QueryClientProvider client={client}>{element}</QueryClientProvider>);
const problem = (code: string, status: number, extra = {}) =>
  HttpResponse.json(
    { type: `urn:motionile:problem:${code}`, title: "Request failed", status, code, ...extra },
    { status },
  );

beforeAll(() => {
  apiClient.defaults.baseURL = window.location.origin;
  server.listen({ onUnhandledFrame: "error" });
});
afterAll(() => {
  if (originalBaseURL === undefined) delete apiClient.defaults.baseURL;
  else apiClient.defaults.baseURL = originalBaseURL;
  server.close();
});
beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useChallengeStore.setState({ challenge: null, purpose: "verify" });
});
afterEach(() => {
  server.resetHandlers();
  client.clear();
});

describe("auth journeys with the contract and HTTP client", () => {
  it("signs in, caches the user and preserves the requested path", async () => {
    server.use(
      http.post(`${api}/login`, async ({ request }) => {
        expect(request.headers.get("X-Turnstile-Token")).toBe("test-token");
        expect(await request.json()).toEqual({
          identifier: "asha@example.com",
          password: "safe-password-123",
        });
        return HttpResponse.json(user);
      }),
    );
    mount(<LoginForm />);
    fireEvent.change(screen.getByLabelText("Email or phone"), {
      target: { value: "ASHA@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password", { exact: true, selector: "input" }), {
      target: { value: "safe-password-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => {
      expect(navigation.replace).toHaveBeenCalledWith("/settings/security");
    });
    expect(client.getQueryData(authKeys.me())).toEqual(user);
  });
  it("routes unverified credentials to verification with masked metadata", async () => {
    server.use(
      http.post(`${api}/login`, () => problem("verification_required", 403, { challenge })),
    );
    mount(<LoginForm />);
    fireEvent.change(screen.getByLabelText("Email or phone"), {
      target: { value: "asha@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password", { exact: true, selector: "input" }), {
      target: { value: "safe-password-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => {
      expect(navigation.push).toHaveBeenCalledWith("/verify?next=%2Fsettings%2Fsecurity");
    });
    expect(useChallengeStore.getState().challenge?.destination).toBe(challenge.destination);
  });
  it("disables submission until Retry-After passes", async () => {
    server.use(
      http.post(`${api}/login`, () =>
        HttpResponse.json(
          { code: "rate_limited" },
          { status: 429, headers: { "Retry-After": "1" } },
        ),
      ),
    );
    mount(<LoginForm />);
    fireEvent.change(screen.getByLabelText("Email or phone"), {
      target: { value: "asha@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password", { exact: true, selector: "input" }), {
      target: { value: "safe-password-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("button", { name: "Try again in 1s" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled(), {
      timeout: 2500,
    });
  });
  it("registers with consent and moves to mandatory verification", async () => {
    server.use(
      http.post(`${api}/register`, async ({ request }) => {
        expect(await request.json()).toEqual({
          name: "Asha",
          email: "asha@example.com",
          password: "safe-password-123",
        });
        return HttpResponse.json(challenge, { status: 202 });
      }),
    );
    mount(<RegisterForm />);
    for (const [label, value] of [
      ["Name", "Asha"],
      ["Email or phone", "asha@example.com"],
      ["Password", "safe-password-123"],
      ["Confirm password", "safe-password-123"],
    ]) {
      if (label && value)
        fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
    }
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => {
      expect(navigation.push).toHaveBeenCalledWith("/verify?next=%2Fsettings%2Fsecurity");
    });
  });
  it("auto-submits a complete verification code once", async () => {
    const received = vi.fn();
    server.use(
      http.post(`${api}/verify`, async ({ request }) => {
        received(await request.json());
        return HttpResponse.json(user);
      }),
    );
    mount(<VerifyForm />);
    fireEvent.change(screen.getByRole("textbox", { name: "Digit 1" }), {
      target: { value: "123456" },
    });
    await waitFor(() => {
      expect(navigation.replace).toHaveBeenCalledWith("/settings/security");
    });
    expect(received).toHaveBeenCalledExactlyOnceWith({ code: "123456" });
  });
  it("resets the password and returns to login with a confirmation", async () => {
    server.use(
      http.post(`${api}/password/reset`, async ({ request }) => {
        expect(await request.json()).toEqual({ code: "123456", newPassword: "new-password-456" });
        return new HttpResponse(null, { status: 204 });
      }),
    );
    mount(<ResetPasswordForm />);
    fireEvent.change(screen.getByRole("textbox", { name: "Digit 1" }), {
      target: { value: "123456" },
    });
    fireEvent.change(screen.getByLabelText("New password", { exact: true }), {
      target: { value: "new-password-456" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password", { exact: true }), {
      target: { value: "new-password-456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
    await waitFor(() => {
      expect(navigation.replace).toHaveBeenCalledWith("/login?reset=success");
    });
  });
});

describe("security settings", () => {
  const session = {
    id: "0199aabb-1111-7111-8111-111111111112",
    current: false,
    deviceLabel: "Other browser",
    ip: "127.0.0.1",
    createdAt: "2026-10-15T00:00:00Z",
    lastUsedAt: "2026-10-15T00:00:00Z",
  };
  it("lists sessions, confirms revocation and refreshes the list", async () => {
    let removed = false;
    server.use(
      http.get(`${api}/me`, () => HttpResponse.json(user)),
      http.get(`${api}/sessions`, () =>
        HttpResponse.json({ items: removed ? [] : [session], nextCursor: null }),
      ),
      http.delete(`${api}/sessions/${session.id}`, () => {
        removed = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    mount(<SecuritySettings />);
    await screen.findByText("Other browser");
    const interaction = userEvent.setup();
    await interaction.click(screen.getByRole("button", { name: "Revoke session" }));
    await interaction.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke session" }),
    );
    await waitFor(() => expect(screen.queryByText("Other browser")).not.toBeInTheDocument());
    expect(removed).toBe(true);
  });
  it("prevents unlinking the only sign-in method", async () => {
    server.use(
      http.get(`${api}/me`, () => HttpResponse.json({ ...user, hasPassword: false, contacts: [] })),
      http.get(`${api}/sessions`, () => HttpResponse.json({ items: [], nextCursor: null })),
    );
    mount(<SecuritySettings />);
    expect(await screen.findByRole("button", { name: "Unlink Google" })).toBeDisabled();
  });
  it("unlinks a provider after confirmation and refreshes the account", async () => {
    let linked = true;
    server.use(
      http.get(`${api}/me`, () =>
        HttpResponse.json({ ...user, linkedProviders: linked ? ["google"] : [] }),
      ),
      http.get(`${api}/sessions`, () => HttpResponse.json({ items: [], nextCursor: null })),
      http.delete(`${api}/oauth/google`, () => {
        linked = false;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    mount(<SecuritySettings />);
    const interaction = userEvent.setup();
    await interaction.click(await screen.findByRole("button", { name: "Unlink Google" }));
    await interaction.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Unlink Google" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Unlink Google" })).not.toBeInTheDocument(),
    );
    expect(linked).toBe(false);
  });
});
