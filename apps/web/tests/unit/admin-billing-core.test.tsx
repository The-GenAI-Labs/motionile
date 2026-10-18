import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { adminBillingNavigation } from "@/config/navigation";
import { AdminBillingNav } from "@/features/admin-billing/components/admin-billing-nav";
import { RevenueView } from "@/features/admin-billing/components/revenue-panel";
import { RunDetail } from "@/features/admin-billing/components/run-detail";
import { WebhookDetail } from "@/features/admin-billing/components/webhook-detail";
import { adminBillingKeys } from "@/features/admin-billing/query-keys";
import { ApiError } from "@/lib/api/api-error";
import { parseRupeesToPaise } from "@/lib/utils/money";

import { EVENT_ID, run, RUN_ID, webhookEvent } from "./admin-billing-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  getReconciliationRun: vi.fn(),
  downloadReconciliationReport: vi.fn(),
  getWebhookEvent: vi.fn(),
  reprocessWebhookEvent: vi.fn(),
}));
const session = vi.hoisted(() => ({ permissions: [] as string[] }));

vi.mock("@/features/admin-billing/api/admin-billing.api", () => api);
vi.mock("@/features/auth/hooks/use-current-user", () => ({
  useCurrentUser: () => ({ data: { permissions: session.permissions }, isPending: false }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/billing/payments",
  useRouter: () => ({ push: vi.fn() }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  session.permissions = [];
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("rupee to paise conversion", () => {
  it("uses integer arithmetic and accepts at most two decimals", () => {
    expect(parseRupeesToPaise("499")).toBe(49_900);
    expect(parseRupeesToPaise("499.5")).toBe(49_950);
    expect(parseRupeesToPaise("0.07")).toBe(7);
    expect(parseRupeesToPaise("19.99")).toBe(1999);
    expect(parseRupeesToPaise("1.005")).toBeNull();
    expect(parseRupeesToPaise("-5")).toBeNull();
    expect(parseRupeesToPaise("1e3")).toBeNull();
    expect(parseRupeesToPaise("")).toBeNull();
  });
});

describe("query keys", () => {
  it("nest every key under the admin billing root and separate filters", () => {
    expect(adminBillingKeys.payment("p1")).toEqual([
      "admin-billing",
      "payments",
      "detail",
      "p1",
      null,
    ]);
    expect(adminBillingKeys.payment("p1", 500)).not.toEqual(adminBillingKeys.payment("p1"));
    expect(adminBillingKeys.productList({ kind: "subscription" })).toEqual([
      "admin-billing",
      "products",
      "list",
      { kind: "subscription" },
    ]);
    expect(adminBillingKeys.userLedger("u1").slice(0, 2)).toEqual(adminBillingKeys.credits());
  });
});

describe("billing navigation", () => {
  it("shows only the sections the permissions allow", () => {
    session.permissions = ["billing.read"];
    render(<AdminBillingNav />);

    const nav = screen.getByRole("navigation", { name: "Billing administration" });
    expect(within(nav).getByRole("link", { name: "Payments" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Reconciliation" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Webhooks" })).not.toBeInTheDocument();
  });

  it("hides the whole section from users without billing permissions and shows webhooks to managers", () => {
    render(<AdminBillingNav />);
    expect(screen.queryAllByRole("link")).toHaveLength(0);

    session.permissions = ["billing.read", "billing.webhooks.manage"];
    render(<AdminBillingNav />);
    expect(screen.getAllByRole("link")).toHaveLength(adminBillingNavigation.length);
  });
});

describe("revenue analytics", () => {
  it("renders the totals, an accessible chart and a table of days", () => {
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(440);
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(800);
    render(
      <RevenueView
        data={{
          currency: "INR",
          rangeStart: "2026-10-16",
          rangeEnd: "2026-10-17",
          totals: {
            capturedPaise: 60_000,
            refundedPaise: 10_000,
            netPaise: 50_000,
            paymentCount: 3,
          },
          days: [
            {
              date: "2026-10-16",
              capturedPaise: 10_000,
              refundedPaise: 20_000,
              netPaise: -10_000,
              paymentCount: 1,
            },
            {
              date: "2026-10-17",
              capturedPaise: 50_000,
              refundedPaise: 0,
              netPaise: 50_000,
              paymentCount: 2,
            },
          ],
        }}
      />,
    );

    expect(
      screen.getByRole("img", { name: /Revenue per day, 2026-10-16 to 2026-10-17/ }),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Revenue per day" });
    expect(within(table).getByRole("cell", { name: "-₹100" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "2026-10-17" })).toBeInTheDocument();
  });
});

describe("webhook reprocess", () => {
  it("asks for confirmation before queueing the event again", async () => {
    const user = userEvent.setup();
    session.permissions = ["billing.webhooks.manage"];
    api.getWebhookEvent.mockResolvedValue(webhookEvent());
    api.reprocessWebhookEvent.mockResolvedValue({
      id: EVENT_ID,
      previousStatus: "failed",
      queued: true,
    });
    renderWithQuery(<WebhookDetail eventId={EVENT_ID} />);

    expect(await screen.findByLabelText("Webhook payload")).toHaveTextContent(
      '"event": "payment.captured"',
    );
    await user.click(screen.getByRole("button", { name: "Reprocess" }));
    expect(api.reprocessWebhookEvent).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Reprocess event" }));

    await waitFor(() => {
      expect(api.reprocessWebhookEvent).toHaveBeenCalledExactlyOnceWith(EVENT_ID);
    });
  });

  it("explains why an event that is still running cannot be reprocessed", async () => {
    api.getWebhookEvent.mockResolvedValue(webhookEvent({ status: "processing" }));
    renderWithQuery(<WebhookDetail eventId={EVENT_ID} />);

    expect(await screen.findByText(/Only failed, processed or ignored events/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reprocess" })).not.toBeInTheDocument();
  });

  it("shows the server error inside the dialog when reprocessing fails", async () => {
    const user = userEvent.setup();
    api.getWebhookEvent.mockResolvedValue(webhookEvent());
    api.reprocessWebhookEvent.mockRejectedValue(
      new ApiError({
        kind: "http",
        status: 409,
        code: "webhook_event_not_reprocessable",
        title: "Conflict",
        detail: null,
      }),
    );
    renderWithQuery(<WebhookDetail eventId={EVENT_ID} />);

    await user.click(await screen.findByRole("button", { name: "Reprocess" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Reprocess event" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This event cannot be reprocessed in its current state.",
    );
  });
});

describe("reconciliation report download", () => {
  it("fetches the report with the API client and saves it as a JSON file", async () => {
    const user = userEvent.setup();
    api.getReconciliationRun.mockResolvedValue(run());
    api.downloadReconciliationReport.mockResolvedValue('{"missing":[]}');
    const createObjectURL = vi.fn(() => "blob:report");
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    renderWithQuery(<RunDetail runId={RUN_ID} />);

    await user.click(await screen.findByRole("button", { name: "Download report" }));

    await waitFor(() => {
      expect(click).toHaveBeenCalledOnce();
    });
    expect(api.downloadReconciliationReport).toHaveBeenCalledExactlyOnceWith(RUN_ID);
    expect(createObjectURL).toHaveBeenCalledOnce();
  });

  it("says when a run has no report", async () => {
    api.getReconciliationRun.mockResolvedValue(run({ hasReport: false }));
    renderWithQuery(<RunDetail runId={RUN_ID} />);

    expect(await screen.findByText("No report was stored for this run.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download report" })).not.toBeInTheDocument();
  });
});
