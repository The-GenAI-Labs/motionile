# 20. GST-inclusive pricing and invoices as a follow-up

- Status: Accepted
- Date: 2026-10-17

## Context

Motionile sells to customers in India, where consumer prices are quoted inclusive of GST. Tax invoices with sequential numbering depend on the business's GST registration, which is not final.

## Decision

- Every price in `products` includes GST and is displayed as "incl. GST". The order and payment amounts equal the product price; there is no separate tax line in the application.
- This phase sends payment receipts (credit pack purchases, subscription activation and renewals, refunds) by email. A receipt is not a tax invoice and is not labelled as one.
- GST tax invoices with sequential numbering are a documented follow-up, to be built once the GST registration, place-of-supply rules and invoice series are decided. The roadmap tracks it.
- `payments.fee_paise` and `payments.tax_paise` record Razorpay's fee and the GST on that fee from settlement data. They are accounting inputs, not customer tax data.

## Consequences

- The checkout amount is exactly the displayed price.
- Retention of billing records already follows the 8-year rule in `docs/db/retention.md`, so invoices can be generated from stored orders and payments later.
- Until invoices ship, finance exports from `orders` and `payments` in the admin console.
