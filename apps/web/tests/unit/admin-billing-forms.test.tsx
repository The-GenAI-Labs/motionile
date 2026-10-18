import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdjustCreditsDialog } from "@/features/admin-billing/components/adjust-credits-dialog";
import { ProductEditForm } from "@/features/admin-billing/components/product-form";
import { RefundDialog } from "@/features/admin-billing/components/refund-dialog";
import { ApiError } from "@/lib/api/api-error";

import {
  PAYMENT_ID,
  paymentDetail,
  PRODUCT_ID,
  productDetail,
  USER_ID,
} from "./admin-billing-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  getPayment: vi.fn(),
  createRefund: vi.fn(),
  adjustUserCredits: vi.fn(),
  updateProduct: vi.fn(),
}));

vi.mock("@/features/admin-billing/api/admin-billing.api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const problem = (code: string, status: number, detail: string | null = null) =>
  new ApiError({ kind: "http", status, code, title: code, detail });

const KEYS = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"];

beforeEach(() => {
  vi.clearAllMocks();
  let next = 0;
  vi.spyOn(globalThis.crypto, "randomUUID").mockImplementation(() => {
    const key = KEYS[next] ?? KEYS[0] ?? "";
    next += 1;
    return key;
  });
});

const openRefund = async (user: ReturnType<typeof userEvent.setup>, payment = paymentDetail()) => {
  api.getPayment.mockResolvedValue(payment);
  renderWithQuery(<RefundDialog payment={payment} />);
  await user.click(screen.getByRole("button", { name: "Refund" }));
  return await screen.findByRole("dialog", { name: "Refund payment" });
};

describe("refund dialog", () => {
  it("defaults to the full refundable amount and its clawback preview", async () => {
    const dialog = await openRefund(userEvent.setup());

    expect(within(dialog).getByRole("textbox", { name: "Refund amount (INR)" })).toHaveValue(
      "499.00",
    );
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "300 credits will be clawed back. Only unused credits of this payment are recovered.",
    );
    expect(api.getPayment).not.toHaveBeenCalledWith(PAYMENT_ID, expect.any(Number));
  });

  it("previews the clawback for a smaller amount through the payment endpoint", async () => {
    const user = userEvent.setup();
    const dialog = await openRefund(user);
    api.getPayment.mockResolvedValue(
      paymentDetail({ clawbackPreview: { amountPaise: 10_000, creditsToClawBack: 60 } }),
    );

    const amount = within(dialog).getByRole("textbox", { name: "Refund amount (INR)" });
    await user.clear(amount);
    await user.type(amount, "100");

    await waitFor(() => {
      expect(api.getPayment).toHaveBeenCalledWith(PAYMENT_ID, 10_000);
    });
    expect(await within(dialog).findByText(/60 credits will be clawed back/)).toBeInTheDocument();
  });

  it("validates the amount and the reason before enabling the refund", async () => {
    const user = userEvent.setup();
    const dialog = await openRefund(user);
    const submit = within(dialog).getByRole("button", { name: "Refund payment" });
    const amount = within(dialog).getByRole("textbox", { name: "Refund amount (INR)" });

    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox", { name: "Reason" }), "Duplicate charge");
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });

    await user.clear(amount);
    await user.type(amount, "600");
    expect(await within(dialog).findByText(/at most 499.00 rupees/)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await user.clear(amount);
    await user.type(amount, "1.234");
    expect(
      await within(dialog).findByText("Enter an amount in rupees with at most two decimals."),
    ).toBeInTheDocument();
  });

  it("reuses the idempotency key when the same request is retried after a transient failure", async () => {
    const user = userEvent.setup();
    const dialog = await openRefund(user);
    api.createRefund
      .mockRejectedValueOnce(problem("payment_provider_unavailable", 503, "Razorpay is down."))
      .mockRejectedValueOnce(
        problem("refund_exceeds_refundable", 422, "At most 100 paise can still be refunded."),
      )
      .mockResolvedValue({ id: PAYMENT_ID });

    await user.type(within(dialog).getByRole("textbox", { name: "Reason" }), "Customer request");
    const submit = within(dialog).getByRole("button", { name: "Refund payment" });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });

    await user.click(submit);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Razorpay is down.");
    await user.click(submit);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "At most 100 paise can still be refunded.",
    );
    await user.click(submit);

    await waitFor(() => {
      expect(api.createRefund).toHaveBeenCalledTimes(3);
    });
    const keys = api.createRefund.mock.calls.map((call) => call[2] as string);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[1]);
    expect(api.createRefund.mock.calls[0]?.[1]).toEqual({
      amountPaise: 49_900,
      reason: "Customer request",
    });
  });
});

describe("adjust credits dialog", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    renderWithQuery(<AdjustCreditsDialog userId={USER_ID} availableCredits={40} />);
    await user.click(screen.getByRole("button", { name: "Adjust credits" }));
    return await screen.findByRole("dialog", { name: "Adjust credits" });
  };

  it("requires a signed whole number and a reason, then sends them with an idempotency key", async () => {
    const user = userEvent.setup();
    const dialog = await open(user);
    api.adjustUserCredits.mockResolvedValue({
      actionId: PAYMENT_ID,
      balanceAfter: 90,
      delta: 50,
      lotId: null,
      userId: USER_ID,
    });
    const submit = within(dialog).getByRole("button", { name: "Apply adjustment" });

    await user.type(within(dialog).getByRole("textbox", { name: "Credits to add or remove" }), "0");
    await user.type(within(dialog).getByRole("textbox", { name: "Reason" }), "Goodwill");
    expect(submit).toBeDisabled();

    const delta = within(dialog).getByRole("textbox", { name: "Credits to add or remove" });
    await user.clear(delta);
    await user.type(delta, "50");
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    await user.click(submit);

    await waitFor(() => {
      expect(api.adjustUserCredits).toHaveBeenCalledExactlyOnceWith(
        USER_ID,
        { delta: 50, reason: "Goodwill" },
        KEYS[0],
      );
    });
  });

  it("shows when a deduction exceeds the available credits", async () => {
    const user = userEvent.setup();
    const dialog = await open(user);
    api.adjustUserCredits.mockRejectedValue(problem("adjustment_exceeds_available", 409));

    await user.type(
      within(dialog).getByRole("textbox", { name: "Credits to add or remove" }),
      "-500",
    );
    await user.type(within(dialog).getByRole("textbox", { name: "Reason" }), "Correction");
    const submit = within(dialog).getByRole("button", { name: "Apply adjustment" });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    await user.click(submit);

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Reserved credits cannot be removed.",
    );
  });
});

describe("product edit form", () => {
  it("locks the financial fields of a product in use and explains why", () => {
    renderWithQuery(
      <ProductEditForm product={productDetail({ isUsed: true })} onReload={vi.fn()} />,
    );

    expect(screen.getByRole("note")).toHaveTextContent(
      "Once an order or subscription uses a product its price, credits, currency and interval cannot change. Duplicate it as a new version to change them; existing subscribers stay on their plan.",
    );
    expect(screen.getByRole("textbox", { name: "Price in rupees (incl. GST)" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Credits granted" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Name" })).toBeEnabled();
  });

  it("sends only the changed fields with the current version and converts rupees to paise", async () => {
    const user = userEvent.setup();
    api.updateProduct.mockResolvedValue(productDetail({ pricePaise: 24_950, version: 4 }));
    renderWithQuery(<ProductEditForm product={productDetail()} onReload={vi.fn()} />);

    const price = screen.getByRole("textbox", { name: "Price in rupees (incl. GST)" });
    await user.clear(price);
    await user.type(price, "249.50");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(api.updateProduct).toHaveBeenCalledExactlyOnceWith(PRODUCT_ID, {
        version: 3,
        pricePaise: 24_950,
      });
    });
  });

  it("blocks saving on a version conflict until the latest version is reloaded", async () => {
    const user = userEvent.setup();
    const onReload = vi.fn();
    api.updateProduct.mockRejectedValue(problem("product_version_conflict", 409));
    renderWithQuery(<ProductEditForm product={productDetail()} onReload={onReload} />);

    await user.type(screen.getByRole("textbox", { name: "Name" }), " Plus");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("changed by someone else");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Reload latest version" }));
    expect(onReload).toHaveBeenCalledOnce();
  });
});
