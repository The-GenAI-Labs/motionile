import { timingSafeEqual } from "node:crypto";

import { revalidateTag } from "next/cache";
import { NextResponse } from "next/server";
import { z } from "zod";

import { serverEnv } from "@/config/server-env";
import { isRevalidatableTag } from "@/lib/revalidation/tags";

const requestSchema = z.object({
  tags: z.array(z.string().trim().min(1).max(200)).min(1).max(50),
});

const matchesSecret = (authorization: string | null, expected: string): boolean => {
  const supplied = authorization?.startsWith("Bearer ") ? authorization.slice(7) : "";
  const suppliedBytes = Buffer.from(supplied);
  const expectedBytes = Buffer.from(expected);
  return (
    suppliedBytes.length === expectedBytes.length && timingSafeEqual(suppliedBytes, expectedBytes)
  );
};

export async function POST(request: Request) {
  const secret = serverEnv.catalogRevalidationSecret;
  if (secret === undefined || !matchesSecret(request.headers.get("authorization"), secret)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const parsed = requestSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }
  const tags = [...new Set(parsed.data.tags)];
  if (!tags.every(isRevalidatableTag)) {
    return NextResponse.json({ error: "Unsupported tag" }, { status: 400 });
  }
  for (const tag of tags) {
    revalidateTag(tag, "max");
  }
  return NextResponse.json({ revalidated: tags });
}
