import {
  zAuthChangePasswordBody,
  zAuthLoginBody,
  zAuthRegisterBody,
  zAuthResetPasswordBody,
  zCodeRequest,
  zIdentifierRequest,
} from "@motionile/api-contract";
import { parsePhoneNumberFromString } from "libphonenumber-js";
import { z } from "zod";

export const normalizeIdentifier = (value: string): string => {
  const trimmed = value.trim();
  if (trimmed.includes("@")) return trimmed.toLowerCase();
  return parsePhoneNumberFromString(trimmed, "IN")?.number ?? trimmed;
};

export const identifierSchema = zIdentifierRequest.shape.identifier
  .trim()
  .refine(
    (value) =>
      value.includes("@")
        ? z.email().safeParse(value).success
        : parsePhoneNumberFromString(value, "IN")?.isValid() === true,
    "Enter a valid email address or phone number.",
  )
  .transform(normalizeIdentifier);
export const loginSchema = zAuthLoginBody.extend({ identifier: identifierSchema });
export const requestCodeSchema = zIdentifierRequest.extend({ identifier: identifierSchema });
export const registerSchema = z
  .object({
    name: zAuthRegisterBody.shape.name.trim(),
    identifier: identifierSchema,
    password: zAuthRegisterBody.shape.password,
    confirmPassword: z.string(),
    terms: z.boolean().refine((value) => value, "Accept the terms to continue."),
  })
  .refine((value) => value.password === value.confirmPassword, {
    path: ["confirmPassword"],
    message: "Passwords do not match.",
  });
export const codeSchema = zCodeRequest;
export const resetPasswordSchema = zAuthResetPasswordBody
  .extend({ confirmPassword: z.string() })
  .refine((value) => value.newPassword === value.confirmPassword, {
    path: ["confirmPassword"],
    message: "Passwords do not match.",
  });
export const changePasswordSchema = zAuthChangePasswordBody
  .extend({ confirmPassword: z.string() })
  .refine((value) => value.newPassword === value.confirmPassword, {
    path: ["confirmPassword"],
    message: "Passwords do not match.",
  });
