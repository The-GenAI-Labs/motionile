import "server-only";

import { zShareGetSharedVideoResponse } from "@motionile/api-contract";
import { cache } from "react";

import { ApiError } from "@/lib/api/api-error";
import { serverFetch } from "@/lib/api/server";

const NOT_FOUND_STATUS = 404;

export const SHARE_SLUG_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export const loadSharedVideo = cache(async (slug: string) => {
  if (!SHARE_SLUG_PATTERN.test(slug)) {
    return null;
  }
  try {
    return await serverFetch(`/v1/share/${slug}`, {
      schema: zShareGetSharedVideoResponse,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === NOT_FOUND_STATUS) {
      return null;
    }
    throw error;
  }
});
