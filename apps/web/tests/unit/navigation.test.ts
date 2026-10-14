import { describe, expect, it } from "vitest";

import {
  adminNavigation,
  appNavigation,
  authPaths,
  crawlerDisallowedPaths,
  footerNavigation,
  isActivePath,
  legalLinks,
  publicNavigation,
  publicPages,
  userNavigation,
} from "@/config/navigation";

const KEBAB_PATH = /^\/([a-z0-9]+(-[a-z0-9]+)*(\/[a-z0-9]+(-[a-z0-9]+)*)*)?$/;

describe("navigation config", () => {
  it("uses lowercase kebab-case paths everywhere", () => {
    const paths = [
      ...publicNavigation.map((item) => item.href),
      ...footerNavigation.flatMap((group) => group.links.map((link) => link.href)),
      ...publicPages.map((page) => page.path),
      ...userNavigation.items.map((item) => item.href),
      ...adminNavigation.items.map((item) => item.href),
      ...authPaths,
    ];

    for (const path of paths) {
      expect(path).toMatch(KEBAB_PATH);
    }
  });

  it("links every public page from the header or footer", () => {
    const linked = new Set([
      ...publicNavigation.map((item) => item.href),
      ...footerNavigation.flatMap((group) => group.links.map((link) => link.href)),
    ]);

    for (const page of publicPages) {
      expect(linked.has(page.path)).toBe(true);
    }
  });

  it("puts the legal pages in the footer", () => {
    expect(legalLinks.map((link) => link.href)).toEqual([
      "/legal/terms",
      "/legal/privacy",
      "/legal/refund-policy",
      "/legal/data-deletion",
    ]);
    expect(footerNavigation.find((group) => group.title === "Legal")?.links).toBe(legalLinks);
  });

  it("keeps app areas unique and scoped", () => {
    expect(appNavigation.user).toBe(userNavigation);
    expect(appNavigation.admin).toBe(adminNavigation);
    for (const area of [userNavigation, adminNavigation]) {
      const hrefs = area.items.map((item) => item.href);
      expect(new Set(hrefs).size).toBe(hrefs.length);
      expect(hrefs).toContain(area.homeHref);
    }
    for (const item of adminNavigation.items) {
      expect(item.href.startsWith("/admin")).toBe(true);
    }
  });

  it("disallows the admin console, the user area and auth pages for crawlers", () => {
    expect(crawlerDisallowedPaths).toEqual(
      expect.arrayContaining([
        "/admin",
        ...userNavigation.items.map((item) => item.href),
        ...authPaths,
      ]),
    );
  });
});

describe("isActivePath", () => {
  it("matches the home item exactly", () => {
    expect(isActivePath("/admin", "/admin", "/admin")).toBe(true);
    expect(isActivePath("/admin/users", "/admin", "/admin")).toBe(false);
  });

  it("matches nested routes for other items", () => {
    expect(isActivePath("/admin/users", "/admin/users", "/admin")).toBe(true);
    expect(isActivePath("/admin/users/123", "/admin/users", "/admin")).toBe(true);
    expect(isActivePath("/admin/users-export", "/admin/users", "/admin")).toBe(false);
    expect(isActivePath("/library", "/settings", "/dashboard")).toBe(false);
  });
});
