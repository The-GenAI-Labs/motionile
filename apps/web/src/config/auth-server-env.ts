import "server-only";

import { z } from "zod";

const values = z
  .object({
    AUTH_JWT_ISSUER: z.url().default("https://api.motionile.local"),
    AUTH_JWT_AUDIENCE: z.string().min(1).default("motionile"),
  })
  .parse({
    AUTH_JWT_ISSUER: process.env.AUTH_JWT_ISSUER,
    AUTH_JWT_AUDIENCE: process.env.AUTH_JWT_AUDIENCE,
  });

export const authServerEnv = { issuer: values.AUTH_JWT_ISSUER, audience: values.AUTH_JWT_AUDIENCE };
