import "server-only";

import { env } from "@/config/env";
import { parseServerEnv } from "@/config/env-schema";

export const serverEnv = parseServerEnv({ API_INTERNAL_URL: process.env.API_INTERNAL_URL }, env);
