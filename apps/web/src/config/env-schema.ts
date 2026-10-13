import { z } from "zod";

export const publicEnvSchema = z.object({
  NEXT_PUBLIC_SITE_URL: z
    .url({ protocol: /^https?$/ })
    .transform((value) => value.replace(/\/+$/, "")),
});

export type PublicEnv = z.infer<typeof publicEnvSchema>;

export const parsePublicEnv = (source: Record<string, string | undefined>): PublicEnv => {
  const result = publicEnvSchema.safeParse(source);
  if (!result.success) {
    throw new Error(`Invalid public environment variables:\n${z.prettifyError(result.error)}`);
  }
  return result.data;
};

export const readPublicEnv = (): PublicEnv =>
  parsePublicEnv({
    NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL,
  });
