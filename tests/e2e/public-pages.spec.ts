import { expect, test } from "@playwright/test";

interface PublicPage {
  path: string;
  heading: string;
  title: RegExp;
}

const PUBLIC_PAGES: PublicPage[] = [
  { path: "/", heading: "Motionile", title: /Motionile/ },
  { path: "/about", heading: "About Motionile", title: /^About · Motionile$/ },
  { path: "/pricing", heading: "Simple, credit-based pricing", title: /^Pricing · Motionile$/ },
  { path: "/contact", heading: "Get in touch", title: /^Contact · Motionile$/ },
  { path: "/legal/terms", heading: "Terms of Service", title: /^Terms of Service · Motionile$/ },
  { path: "/legal/privacy", heading: "Privacy Policy", title: /^Privacy Policy · Motionile$/ },
  {
    path: "/legal/refund-policy",
    heading: "Refund and Cancellation Policy",
    title: /^Refund and Cancellation Policy · Motionile$/,
  },
];

interface LinkedData {
  "@type": string;
}

const PRIVATE_PREFIXES = ["/admin", "/dashboard", "/library", "/settings", "/login", "/register"];

for (const publicPage of PUBLIC_PAGES) {
  test(`${publicPage.path} has complete SEO metadata`, async ({ page }) => {
    const response = await page.goto(publicPage.path);

    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle(publicPage.title);
    await expect(page.getByRole("heading", { level: 1, name: publicPage.heading })).toBeVisible();

    const canonical = await page.locator('link[rel="canonical"]').getAttribute("href");
    expect(canonical).not.toBeNull();
    expect(new URL(canonical ?? "").pathname.replace(/\/$/, "")).toBe(
      publicPage.path.replace(/\/$/, ""),
    );

    const description = await page.locator('meta[name="description"]').getAttribute("content");
    expect(description?.length ?? 0).toBeGreaterThan(40);

    for (const property of ["og:title", "og:description", "og:url", "og:image", "og:type"]) {
      await expect(page.locator(`meta[property="${property}"]`)).toHaveAttribute("content", /.+/);
    }
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", /.+/);
  });
}

test("descriptions and canonical URLs are unique", async ({ page }) => {
  const descriptions = new Set<string>();
  const canonicals = new Set<string>();

  for (const publicPage of PUBLIC_PAGES) {
    await page.goto(publicPage.path);
    descriptions.add(
      (await page.locator('meta[name="description"]').getAttribute("content")) ?? "",
    );
    canonicals.add((await page.locator('link[rel="canonical"]').getAttribute("href")) ?? "");
  }

  expect(descriptions.size).toBe(PUBLIC_PAGES.length);
  expect(canonicals.size).toBe(PUBLIC_PAGES.length);
});

test("home page publishes Organization and SoftwareApplication JSON-LD", async ({ page }) => {
  await page.goto("/");

  const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
  const types = blocks
    .flatMap((block) => [JSON.parse(block) as LinkedData | LinkedData[]].flat())
    .map((node) => node["@type"]);

  expect(types).toEqual(expect.arrayContaining(["Organization", "SoftwareApplication"]));
});

test("legal pages are flagged as drafts pending legal review", async ({ page }) => {
  for (const path of ["/legal/terms", "/legal/privacy", "/legal/refund-policy"]) {
    await page.goto(path);

    await expect(page.getByText(/pending legal review/i).first()).toBeVisible();
  }
});

test("robots.txt allows public pages and blocks private areas", async ({ request }) => {
  const body = await (await request.get("/robots.txt")).text();

  expect(body).toContain("Allow: /");
  for (const prefix of PRIVATE_PREFIXES) {
    expect(body).toContain(`Disallow: ${prefix}`);
  }
  expect(body).toMatch(/Sitemap: .+\/sitemap\.xml/);
});

test("sitemap.xml lists every public page", async ({ request }) => {
  const body = await (await request.get("/sitemap.xml")).text();
  const locations = [...body.matchAll(/<loc>([^<]+)<\/loc>/g)].map(
    (match) => new URL(match[1] ?? "").pathname,
  );

  for (const publicPage of PUBLIC_PAGES) {
    expect(locations).toContain(publicPage.path);
  }
  for (const prefix of PRIVATE_PREFIXES) {
    expect(locations.some((location) => location.startsWith(prefix))).toBe(false);
  }
});

test("header and footer navigation reach every public page", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("banner").getByRole("link", { name: "Pricing" }).click();
  await expect(page).toHaveURL(/\/pricing$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Simple, credit-based pricing" }),
  ).toBeVisible();

  for (const [name, path] of [
    ["Terms of Service", "/legal/terms"],
    ["Privacy Policy", "/legal/privacy"],
    ["Refund and Cancellation Policy", "/legal/refund-policy"],
  ] as const) {
    await page.getByRole("contentinfo").getByRole("link", { name }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
  }
});

test("unknown pages render the designed not-found page with a 404", async ({ page }) => {
  const response = await page.goto("/this-page-does-not-exist");

  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: /home/i }).first()).toBeVisible();
});

test("public pages are served from the static cache", async ({ request }) => {
  for (const publicPage of PUBLIC_PAGES) {
    const response = await request.get(publicPage.path);

    expect(
      response.headers()["x-nextjs-cache"] ?? response.headers()["x-nextjs-prerender"],
    ).toBeDefined();
  }
});
