import "server-only";

import { cache } from "react";

import { makeQueryClient } from "@/lib/query/query-client";

export const getServerQueryClient = cache(makeQueryClient);
