import { check, sleep } from "k6";
import crypto from "k6/crypto";
import http from "k6/http";

import { loadOptions } from "../thresholds.js";

const apiBaseUrl = __ENV.API_BASE_URL || "http://localhost:8000";
const webhookSecret =
  __ENV.RAZORPAY_WEBHOOK_SECRET || "motionile-development-razorpay-webhook-secret";
const runId = Date.now().toString(36);

export const options = loadOptions();

function unknownOrderFailure(suffix) {
  const createdAt = Math.floor(Date.now() / 1000);
  return JSON.stringify({
    entity: "event",
    account_id: "acc_motionile_load",
    event: "payment.failed",
    contains: ["payment"],
    payload: {
      payment: {
        entity: {
          id: `pay_load${suffix}`,
          entity: "payment",
          amount: 19900,
          currency: "INR",
          status: "failed",
          order_id: `order_load${suffix}`,
          method: "card",
          captured: false,
          amount_refunded: 0,
          refund_status: null,
          fee: null,
          tax: null,
          notes: {},
          created_at: createdAt,
        },
      },
    },
    created_at: createdAt,
  });
}

function deliver(body, eventId) {
  return http.post(`${apiBaseUrl}/v1/webhooks/razorpay`, body, {
    headers: {
      "Content-Type": "application/json",
      "X-Razorpay-Signature": crypto.hmac("sha256", webhookSecret, body, "hex"),
      "X-Razorpay-Event-Id": eventId,
    },
    tags: { name: "razorpay webhook" },
  });
}

function receiptOf(response) {
  return response.json("status");
}

export default function billingWebhooks() {
  const suffix = `${runId}${__VU}x${__ITER}`;
  const eventId = `evt_load_${suffix}`;
  const body = unknownOrderFailure(suffix);

  const first = deliver(body, eventId);
  check(first, {
    "webhook is accepted": (result) => result.status === 200,
    "webhook is received": (result) => receiptOf(result) === "received",
  });

  const replay = deliver(body, eventId);
  check(replay, {
    "replayed webhook is accepted": (result) => result.status === 200,
    "replayed webhook is a duplicate": (result) => receiptOf(result) === "duplicate",
  });

  sleep(0.5);
}
