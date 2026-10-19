import { randomBytes } from "node:crypto";

import { expect, test } from "@playwright/test";

import { signupWithRole } from "../../support/admin.js";

const REVALIDATION_SECRET =
  process.env["CATALOG_REVALIDATION_SECRET"] ?? "motionile-ci-catalog-revalidation-secret";
const PRODUCTS_TAG = "billing-products";

interface AdminProduct {
  id: string;
  code: string;
  isActive: boolean;
}

test("the pricing page lists a credit pack once an admin creates it and the products tag is revalidated", async ({
  page,
  request,
}) => {
  test.setTimeout(180000);
  const admin = await signupWithRole(request, "super_admin");
  const suffix = randomBytes(4).toString("hex");
  const name = `E2E Pack ${suffix}`;
  const code = `e2e_pack_${suffix}`;

  const created = await admin.json<AdminProduct>(
    await admin.call("POST", "/v1/admin/billing/products", {
      code,
      kind: "credit_pack",
      name,
      description: "Created by the billing end-to-end suite.",
      pricePaise: 12300,
      creditsGranted: 77,
      isActive: true,
    }),
    201,
  );
  expect(created.isActive).toBe(true);

  await expect
    .poll(async () => (await admin.products()).creditPacks.map((pack) => pack.code), {
      timeout: 30000,
      intervals: [250, 500, 1000],
    })
    .toContain(code);

  const revalidation = await request.post("/api/revalidate", {
    headers: { Authorization: `Bearer ${REVALIDATION_SECRET}` },
    data: { tags: [PRODUCTS_TAG] },
  });
  expect(revalidation.status()).toBe(200);

  await expect(async () => {
    await page.goto("/pricing");
    await expect(page.getByRole("heading", { name, level: 3 })).toBeVisible({ timeout: 3000 });
  }).toPass({ timeout: 60000, intervals: [1000, 2000, 3000] });

  const card = page.getByRole("article", { name, exact: true });
  await expect(card).toContainText("77 credits that never expire");
  await expect(card).toContainText("Created by the billing end-to-end suite.");
});
