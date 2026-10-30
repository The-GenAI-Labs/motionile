import "server-only";

import { zShareGetSharedVideoResponse } from "@motionile/api-contract";
import { cache } from "react";

import { SHARE_SLUG_PATTERN } from "@/features/library/schemas/library.schema";
import { ApiError } from "@/lib/api/api-error";
import { serverFetch } from "@/lib/api/server";

const NOT_FOUND_STATUS = 404;

export const SHARE_INTERNAL_HEADER = "X-Motionile-Internal";

const internalHeaders = (): Record<string, string> => {
  const secret = process.env.SHARE_INTERNAL_SECRET;
  if (secret !== undefined && secret !== "") {
    return { [SHARE_INTERNAL_HEADER]: secret };
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error("SHARE_INTERNAL_SECRET is not set; shared video pages cannot be loaded.");
  }
  process.stderr.write(
    "SHARE_INTERNAL_SECRET is not set; the API will treat this server as one anonymous visitor.\n",
  );
  return {};
};

export const loadSharedVideo = cache(async (slug: string) => {
  if (!SHARE_SLUG_PATTERN.test(slug)) {
    return null;
  }
  const headers = internalHeaders();
  try {
    return await serverFetch(`/v1/share/${slug}`, {
      schema: zShareGetSharedVideoResponse,
      cache: "no-store",
      headers,
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === NOT_FOUND_STATUS) {
      return null;
    }
    throw error;
  }
});
