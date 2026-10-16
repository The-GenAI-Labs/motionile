import "server-only";

import { createRemoteJWKSet, errors, jwtVerify } from "jose";
import { cookies } from "next/headers";
import { z } from "zod";

import { authServerEnv } from "@/config/auth-server-env";
import { env } from "@/config/env";

const principalSchema = z.object({
  sub: z.uuid(),
  sid: z.uuid(),
  roles: z.array(z.string()),
  exp: z.number().int(),
});

export interface Principal {
  id: string;
  sessionId: string;
  roles: string[];
  expiry: number;
}

export type Session = { status: "valid"; principal: Principal } | { status: "expired" | "none" };

const keys = createRemoteJWKSet(
  new URL(env.NEXT_PUBLIC_JWKS_URL ?? `${env.NEXT_PUBLIC_API_URL}/v1/auth/jwks.json`),
);

export async function readSession(): Promise<Session> {
  const token = (await cookies()).get("__Secure-mo_at")?.value;
  if (!token) return { status: "none" };
  try {
    const { payload } = await jwtVerify(token, keys, {
      algorithms: ["EdDSA"],
      issuer: authServerEnv.issuer,
      audience: authServerEnv.audience,
      requiredClaims: ["sub", "sid", "roles", "exp", "iat", "jti"],
      clockTolerance: 5,
    });
    const claims = principalSchema.parse(payload);
    return {
      status: "valid",
      principal: { id: claims.sub, sessionId: claims.sid, roles: claims.roles, expiry: claims.exp },
    };
  } catch (error) {
    if (error instanceof errors.JWTExpired) return { status: "expired" };
    if (error instanceof errors.JOSEError || error instanceof z.ZodError) return { status: "none" };
    throw error;
  }
}
