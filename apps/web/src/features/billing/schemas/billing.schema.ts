import { zCreateOrderRequest, zIntervalName } from "@motionile/api-contract";
import { z } from "zod";

export const productCodeSchema = zCreateOrderRequest.shape.productCode;

export const billingIntervalSchema = zIntervalName;

export const idempotencyKeySchema = z.string().regex(/^[\x21-\x7E]{1,255}$/);

export const orderIdSchema = z.uuid();

export const parseProductCode = (value: unknown): string | null => {
  const parsed = productCodeSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
};
