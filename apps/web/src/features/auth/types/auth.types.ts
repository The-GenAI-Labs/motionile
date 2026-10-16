import type {
  zAuthUnlinkOauthPath,
  zChallengeResponse,
  zSessionUser,
} from "@motionile/api-contract";
import type { z } from "zod";

export type AuthUser = z.infer<typeof zSessionUser>;
export type AuthChallenge = z.infer<typeof zChallengeResponse>;
export type OAuthProvider = z.infer<typeof zAuthUnlinkOauthPath>["provider"];
