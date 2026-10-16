import { z } from "zod";

export const profileFormSchema = z.object({
  name: z.string().trim().min(1, "Enter your name.").max(120),
});

export const contactFormSchema = z.object({
  identifier: z.string().trim().min(3, "Enter an email address or phone number.").max(254),
});

export const deletionCodeSchema = z.object({
  code: z.string().regex(/^\d{6}$/, "Enter the six-digit code."),
});

export type ProfileFormValues = z.infer<typeof profileFormSchema>;
