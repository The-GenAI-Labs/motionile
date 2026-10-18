export const BILLING_PRODUCTS_TAG = "billing-products";

const CATALOG_TAG_PATTERN = /^catalog(:[A-Za-z0-9_./:-]{1,190})?$/;

export const isRevalidatableTag = (tag: string): boolean =>
  tag === BILLING_PRODUCTS_TAG || CATALOG_TAG_PATTERN.test(tag);
