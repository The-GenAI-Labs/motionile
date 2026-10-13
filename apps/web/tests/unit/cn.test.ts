import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils/cn";

describe("cn", () => {
  it("joins class names and drops falsy values", () => {
    const hiddenWhen = (condition: boolean) => condition && "hidden";

    expect(cn("px-2", hiddenWhen(false), undefined, "text-sm")).toBe("px-2 text-sm");
  });

  it("lets later tailwind utilities win conflicts", () => {
    expect(cn("px-2 py-1", "px-4")).toBe("py-1 px-4");
  });

  it("supports conditional object syntax", () => {
    expect(cn({ "font-medium": true, underline: false })).toBe("font-medium");
  });
});
