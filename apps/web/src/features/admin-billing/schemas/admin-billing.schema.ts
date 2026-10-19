import { zIntervalName, zProductKindName } from "@motionile/api-contract";
import { z } from "zod";

import type {
  AdminProductDetail,
  FlagReason,
  ProductInterval,
  ProductKind,
  RunType,
} from "@/features/admin-billing/types/admin-billing.types";
import { paiseToDecimalString } from "@/lib/utils/format";
import { parseRupeesToPaise, RUPEE_INPUT_MESSAGE, rupeesToPaise } from "@/lib/utils/money";

export const MAX_PRICE_PAISE = 10_000_000_000;
export const MAX_PRODUCT_CREDITS = 100_000_000;
export const MAX_SORT_ORDER = 100_000;
export const MAX_FEATURES = 20;
export const MAX_FEATURE_LENGTH = 120;
export const MAX_ADJUSTMENT = 1_000_000;
export const MAX_REASON_LENGTH = 500;

const CODE_PATTERN = /^[a-z0-9]+(_[a-z0-9]+)*$/;
const INTEGER_PATTERN = /^\d{1,12}$/;
const SIGNED_INTEGER_PATTERN = /^-?\d{1,12}$/;

export const productKindLabels = {
  credit_pack: "Credit pack",
  subscription: "Subscription",
} as const satisfies Record<ProductKind, string>;

export const intervalLabels = {
  month: "Monthly",
  year: "Yearly",
} as const satisfies Record<ProductInterval, string>;

export const flagReasonLabels = {
  amount_mismatch: "Amount mismatch",
  currency_mismatch: "Currency mismatch",
  duplicate_payment: "Duplicate payment",
} as const satisfies Record<FlagReason, string>;

export const flagGuidance = {
  amount_mismatch:
    "The captured amount differs from the order amount, so no credits were granted. Check the payment at Razorpay and refund it if the customer should not be charged.",
  currency_mismatch:
    "The payment currency differs from the order currency, so no credits were granted. Check the payment at Razorpay and refund it if the customer should not be charged.",
  duplicate_payment:
    "Another payment was captured for an order that was already paid. Refund the extra payment from its payment page.",
} as const satisfies Record<FlagReason, string>;

export const runTypeLabels = {
  pending_orders: "Pending orders",
  subscriptions: "Subscription sync",
  settlement: "Settlement check",
} as const satisfies Record<RunType, string>;

export const IMMUTABILITY_EXPLANATION =
  "Once an order or subscription uses a product its price, credits, currency and interval cannot change. Duplicate it as a new version to change them; existing subscribers stay on their plan.";

export const priceFieldSchema = z
  .string()
  .trim()
  .superRefine((value, ctx) => {
    const paise = parseRupeesToPaise(value);
    if (paise === null) {
      ctx.addIssue({ code: "custom", message: RUPEE_INPUT_MESSAGE });
    } else if (paise < 1 || paise > MAX_PRICE_PAISE) {
      ctx.addIssue({ code: "custom", message: "Enter a price above zero." });
    }
  });

const boundedInteger = (label: string, min: number, max: number) =>
  z
    .string()
    .trim()
    .superRefine((value, ctx) => {
      if (!INTEGER_PATTERN.test(value)) {
        ctx.addIssue({ code: "custom", message: `${label} must be a whole number.` });
        return;
      }
      const parsed = Number(value);
      if (parsed < min || parsed > max) {
        ctx.addIssue({
          code: "custom",
          message: `${label} must be between ${String(min)} and ${String(max)}.`,
        });
      }
    });

export const splitLines = (value: string): string[] =>
  value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");

const featuresFieldSchema = z.string().superRefine((value, ctx) => {
  const lines = splitLines(value);
  if (lines.length > MAX_FEATURES) {
    ctx.addIssue({ code: "custom", message: `Add at most ${String(MAX_FEATURES)} features.` });
  }
  if (lines.some((line) => line.length > MAX_FEATURE_LENGTH)) {
    ctx.addIssue({
      code: "custom",
      message: `Keep each feature under ${String(MAX_FEATURE_LENGTH + 1)} characters.`,
    });
  }
});

export const productFormSchema = z
  .object({
    kind: zProductKindName,
    code: z
      .string()
      .trim()
      .min(1, "Enter a product code.")
      .max(60, "Use at most 60 characters.")
      .regex(CODE_PATTERN, "Use lowercase letters and digits separated by single underscores."),
    name: z.string().trim().min(1, "Enter a name.").max(80, "Use at most 80 characters."),
    description: z.string().trim().max(500, "Use at most 500 characters."),
    price: priceFieldSchema,
    creditsGranted: boundedInteger("Credits", 1, MAX_PRODUCT_CREDITS),
    interval: z.union([zIntervalName, z.literal("")]),
    planKey: z.string().trim().max(60, "Use at most 60 characters."),
    features: featuresFieldSchema,
    sortOrder: boundedInteger("Sort order", 0, MAX_SORT_ORDER),
    isActive: z.boolean(),
  })
  .superRefine((value, ctx) => {
    if (value.kind !== "subscription") {
      return;
    }
    if (value.interval === "") {
      ctx.addIssue({ code: "custom", path: ["interval"], message: "Choose a billing interval." });
    }
    if (!CODE_PATTERN.test(value.planKey)) {
      ctx.addIssue({
        code: "custom",
        path: ["planKey"],
        message: "Enter a plan key shared by the monthly and yearly products of one plan.",
      });
    }
  });

export type ProductFormValues = z.infer<typeof productFormSchema>;

export const emptyProductFormValues = (kind: ProductKind): ProductFormValues => ({
  kind,
  code: "",
  name: "",
  description: "",
  price: "",
  creditsGranted: "",
  interval: kind === "subscription" ? "month" : "",
  planKey: "",
  features: "",
  sortOrder: "0",
  isActive: false,
});

export const productFormValues = (product: AdminProductDetail): ProductFormValues => ({
  kind: product.kind,
  code: product.code,
  name: product.name,
  description: product.description ?? "",
  price: paiseToDecimalString(product.pricePaise),
  creditsGranted: String(product.creditsGranted),
  interval: product.interval ?? "",
  planKey: product.planKey ?? "",
  features: product.features.join("\n"),
  sortOrder: String(product.sortOrder),
  isActive: product.isActive,
});

const subscriptionFields = (values: ProductFormValues) =>
  values.interval === "" ? {} : { interval: values.interval, planKey: values.planKey };

export const toCreateProductRequest = (values: ProductFormValues) => ({
  code: values.code,
  kind: values.kind,
  name: values.name,
  pricePaise: rupeesToPaise(values.price),
  creditsGranted: Number(values.creditsGranted),
  sortOrder: Number(values.sortOrder),
  features: splitLines(values.features),
  ...(values.description === "" ? {} : { description: values.description }),
  ...(values.kind === "subscription" ? subscriptionFields(values) : { isActive: values.isActive }),
});

export const toUpdateProductRequest = (
  values: ProductFormValues,
  product: AdminProductDetail,
  financialLocked: boolean,
) => {
  const patch: {
    version: number;
    name?: string;
    description?: string;
    features?: string[];
    sortOrder?: number;
    pricePaise?: number;
    creditsGranted?: number;
    interval?: ProductInterval;
    planKey?: string;
  } = { version: product.version };
  if (values.name !== product.name) {
    patch.name = values.name;
  }
  if (values.description !== "" && values.description !== (product.description ?? "")) {
    patch.description = values.description;
  }
  const features = splitLines(values.features);
  if (features.join("\n") !== product.features.join("\n")) {
    patch.features = features;
  }
  if (Number(values.sortOrder) !== product.sortOrder) {
    patch.sortOrder = Number(values.sortOrder);
  }
  if (financialLocked) {
    return patch;
  }
  const pricePaise = rupeesToPaise(values.price);
  if (pricePaise !== product.pricePaise) {
    patch.pricePaise = pricePaise;
  }
  if (Number(values.creditsGranted) !== product.creditsGranted) {
    patch.creditsGranted = Number(values.creditsGranted);
  }
  if (values.interval !== "" && values.interval !== product.interval) {
    patch.interval = values.interval;
  }
  if (values.planKey !== "" && values.planKey !== (product.planKey ?? "")) {
    patch.planKey = values.planKey;
  }
  return patch;
};

export const duplicateFormSchema = z.object({
  name: z.string().trim().min(1, "Enter a name.").max(80, "Use at most 80 characters."),
  description: z.string().trim().max(500, "Use at most 500 characters."),
  price: priceFieldSchema,
  creditsGranted: boundedInteger("Credits", 1, MAX_PRODUCT_CREDITS),
  interval: z.union([zIntervalName, z.literal("")]),
});

export type DuplicateFormValues = z.infer<typeof duplicateFormSchema>;

export const duplicateFormValues = (product: AdminProductDetail): DuplicateFormValues => ({
  name: product.name,
  description: product.description ?? "",
  price: paiseToDecimalString(product.pricePaise),
  creditsGranted: String(product.creditsGranted),
  interval: product.interval ?? "",
});

export const toDuplicateRequest = (values: DuplicateFormValues, product: AdminProductDetail) => {
  const overrides: {
    name?: string;
    description?: string;
    pricePaise?: number;
    creditsGranted?: number;
    interval?: ProductInterval;
  } = {};
  if (values.name !== product.name) {
    overrides.name = values.name;
  }
  if (values.description !== "" && values.description !== (product.description ?? "")) {
    overrides.description = values.description;
  }
  const pricePaise = rupeesToPaise(values.price);
  if (pricePaise !== product.pricePaise) {
    overrides.pricePaise = pricePaise;
  }
  if (Number(values.creditsGranted) !== product.creditsGranted) {
    overrides.creditsGranted = Number(values.creditsGranted);
  }
  if (values.interval !== "" && values.interval !== product.interval) {
    overrides.interval = values.interval;
  }
  return overrides;
};

export const refundFormSchema = (refundablePaise: number) =>
  z.object({
    amount: z.string().superRefine((value, ctx) => {
      const paise = parseRupeesToPaise(value);
      if (paise === null) {
        ctx.addIssue({ code: "custom", message: RUPEE_INPUT_MESSAGE });
      } else if (paise < 1) {
        ctx.addIssue({ code: "custom", message: "Enter an amount above zero." });
      } else if (paise > refundablePaise) {
        ctx.addIssue({
          code: "custom",
          message: `You can refund at most ${paiseToDecimalString(refundablePaise)} rupees.`,
        });
      }
    }),
    reason: z
      .string()
      .trim()
      .min(1, "Enter a reason for the refund.")
      .max(MAX_REASON_LENGTH, `Use at most ${String(MAX_REASON_LENGTH)} characters.`),
  });

export type RefundFormValues = z.infer<ReturnType<typeof refundFormSchema>>;

export const adjustFormSchema = z
  .object({
    delta: z
      .string()
      .trim()
      .superRefine((value, ctx) => {
        if (!SIGNED_INTEGER_PATTERN.test(value)) {
          ctx.addIssue({ code: "custom", message: "Enter a whole number, for example 50 or -20." });
          return;
        }
        const parsed = Number(value);
        if (parsed === 0 || Math.abs(parsed) > MAX_ADJUSTMENT) {
          ctx.addIssue({
            code: "custom",
            message: `Enter a non-zero number up to ${String(MAX_ADJUSTMENT)} in either direction.`,
          });
        }
      }),
    reason: z
      .string()
      .trim()
      .min(1, "Enter a reason for the adjustment.")
      .max(MAX_REASON_LENGTH, `Use at most ${String(MAX_REASON_LENGTH)} characters.`),
    expiresAt: z.string(),
  })
  .superRefine((value, ctx) => {
    if (value.expiresAt === "") {
      return;
    }
    if (Number(value.delta) < 0) {
      ctx.addIssue({
        code: "custom",
        path: ["expiresAt"],
        message: "Only a grant can have an expiry. Leave it empty for a deduction.",
      });
    } else if (
      Number.isNaN(Date.parse(value.expiresAt)) ||
      Date.parse(value.expiresAt) <= Date.now()
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["expiresAt"],
        message: "Choose an expiry in the future.",
      });
    }
  });

export type AdjustFormValues = z.infer<typeof adjustFormSchema>;

export const toAdjustRequest = (values: AdjustFormValues) => ({
  delta: Number(values.delta),
  reason: values.reason,
  ...(values.expiresAt === "" ? {} : { expiresAt: new Date(values.expiresAt).toISOString() }),
});

export const DEFAULT_RANGE_DAYS = 30;

const toIsoDate = (date: Date): string => date.toISOString().slice(0, 10);

export const defaultDateRange = (now: Date = new Date(), days: number = DEFAULT_RANGE_DAYS) => {
  const start = new Date(now);
  start.setUTCDate(start.getUTCDate() - (days - 1));
  return { from: toIsoDate(start), to: toIsoDate(now) };
};

export const MAX_RANGE_DAYS = 366;

export const rangeDays = (from: string, to: string): number =>
  Math.floor((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1;

export const isValidDateRange = (from: string, to: string): boolean => {
  if (Number.isNaN(Date.parse(from)) || Number.isNaN(Date.parse(to))) {
    return false;
  }
  const days = rangeDays(from, to);
  return days >= 1 && days <= MAX_RANGE_DAYS;
};
