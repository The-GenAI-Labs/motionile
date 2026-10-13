import { describe, expect, it } from "vitest";
import { z } from "zod";

import { cursorPageSchema, flattenCursorPages, getNextPageParam } from "@/lib/api/pagination";

describe("cursor pagination helpers", () => {
  it("validates cursor pages", () => {
    const schema = cursorPageSchema(z.object({ id: z.string() }));

    expect(schema.parse({ items: [{ id: "a" }], nextCursor: "c1" })).toEqual({
      items: [{ id: "a" }],
      nextCursor: "c1",
    });
    expect(schema.parse({ items: [] })).toEqual({ items: [] });
    expect(() => schema.parse({ items: [{ id: 1 }] })).toThrow();
  });

  it("returns the next cursor or undefined on the last page", () => {
    expect(getNextPageParam({ items: [], nextCursor: "abc" })).toBe("abc");
    expect(getNextPageParam({ items: [], nextCursor: null })).toBeUndefined();
    expect(getNextPageParam({ items: [] })).toBeUndefined();
  });

  it("flattens infinite query pages", () => {
    expect(
      flattenCursorPages([
        { items: [1, 2], nextCursor: "x" },
        { items: [3], nextCursor: null },
      ]),
    ).toEqual([1, 2, 3]);
    expect(flattenCursorPages(undefined)).toEqual([]);
  });
});
