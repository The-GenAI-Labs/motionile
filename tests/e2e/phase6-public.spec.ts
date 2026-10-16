import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

interface CatalogPath {
  path: string;
  lastModified: string;
}

interface CatalogPaths {
  items: CatalogPath[];
}

const apiBaseUrl = process.env["API_BASE_URL"] ?? "http://localhost:8000";

test("explore pages publish canonical metadata and breadcrumb JSON-LD", async ({
  page,
  request,
}) => {
  const pathsResponse = await request.get(`${apiBaseUrl}/v1/catalog/paths`);
  expect(pathsResponse.status()).toBe(200);
  const catalog = (await pathsResponse.json()) as CatalogPaths;
  const representative = new Map<number, CatalogPath>();
  for (const item of catalog.items) {
    const depth = item.path.split("/").filter(Boolean).length;
    if (!representative.has(depth)) representative.set(depth, item);
  }
  expect([...representative.keys()]).toEqual(expect.arrayContaining([2, 3, 4]));

  for (const path of ["/explore", ...[...representative.values()].map((item) => item.path)]) {
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);
    const canonical = await page.locator('link[rel="canonical"]').getAttribute("href");
    expect(new URL(canonical ?? "").pathname.replace(/\/$/, "")).toBe(path.replace(/\/$/, ""));
    await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /\S{20,}/);
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute("content", /\S+/);
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toBeVisible();
    const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
    const types = blocks.map((block) => (JSON.parse(block) as { "@type"?: string })["@type"]);
    expect(types).toContain("BreadcrumbList");
  }
});

test("sitemap lists every active catalog path with last-modified values", async ({ request }) => {
  const pathsResponse = await request.get(`${apiBaseUrl}/v1/catalog/paths`);
  const catalog = (await pathsResponse.json()) as CatalogPaths;
  const sitemap = await (await request.get("/sitemap.xml")).text();
  const locations = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map(
    (match) => new URL(match[1] ?? "").pathname,
  );
  const modified = [...sitemap.matchAll(/<lastmod>([^<]+)<\/lastmod>/g)].map(
    (match) => match[1] ?? "",
  );
  for (const item of catalog.items) {
    expect(locations).toContain(item.path);
    expect(Number.isNaN(Date.parse(item.lastModified))).toBe(false);
  }
  expect(modified.length).toBeGreaterThanOrEqual(catalog.items.length);
  expect(modified.every((value) => !Number.isNaN(Date.parse(value)))).toBe(true);
});

test("explore pages have no serious or critical accessibility violations", async ({
  page,
  request,
}) => {
  const pathsResponse = await request.get(`${apiBaseUrl}/v1/catalog/paths`);
  const catalog = (await pathsResponse.json()) as CatalogPaths;
  const deepest = catalog.items.find((item) => item.path.split("/").filter(Boolean).length === 4);
  for (const path of ["/explore", deepest?.path].filter((value): value is string =>
    Boolean(value),
  )) {
    await page.goto(path);
    const report = await new AxeBuilder({ page }).analyze();
    expect(
      report.violations.filter((violation) =>
        ["serious", "critical"].includes(violation.impact ?? ""),
      ),
    ).toEqual([]);
  }
});

test("catalog revalidation rejects missing and incorrect secrets", async ({ request }) => {
  for (const headers of [{}, { Authorization: "Bearer incorrect-revalidation-secret" }]) {
    const response = await request.post("/api/revalidate", {
      headers,
      data: { tags: ["catalog"] },
    });
    expect(response.status()).toBe(401);
  }
});
