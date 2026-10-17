# 19. Product immutability and versioning

- Status: Accepted
- Date: 2026-10-17
- Refines: [ADR 0004](0004-razorpay-billing-with-credit-ledger.md)

## Context

Orders snapshot the price and credits, but subscriptions renew against a Razorpay plan whose amount Razorpay fixes at creation. Editing a product's price or credits after customers have bought it would make `products` disagree with what customers were charged and with the plan at Razorpay.

## Decision

- Once any order or subscription references a product, its `kind`, `price_paise`, `currency`, `interval`, `credits_granted` and `razorpay_plan_id` cannot change. The service rejects the edit with `product_immutable`; a trigger on `products` is the backstop.
- Changing a price means duplicating the product as a new version: a new code (`<base>_v<n>`), `version` increased by one, `supersedes_product_id` pointing at the source, a new Razorpay plan, then deactivating the old product.
- Existing subscribers stay on their plan until they change it. Deactivated products stay readable by the subscriptions and orders that reference them.
- Unused products can be edited freely and their `version` increments on every edit.
- Subscription products carry a `plan_key`, shared by the monthly and yearly products of one plan; at most one active product exists per `plan_key` and interval.
- A subscription product can be activated only after its Razorpay plan has been created by the plan sync.
- The client sends only a product code. Prices, credits and plan IDs are read from the database.

## Consequences

- A product row always explains the money collected under it.
- Price changes are explicit, auditable events instead of edits.
- Admins see a short-lived pair of products during a price change; the admin form explains the rule.
