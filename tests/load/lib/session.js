import { check, sleep } from "k6";
import http from "k6/http";

export const api = __ENV.API_BASE_URL || "http://localhost:8000";
export const origin = __ENV.WEB_BASE_URL || "http://localhost:3000";

const INBOX_ATTEMPTS = 40;
const INBOX_PAUSE_SECONDS = 0.5;
const ADDRESS_BLOCK = 250;

export function newSession(index) {
  const block = Math.floor(index / ADDRESS_BLOCK) % ADDRESS_BLOCK;
  return { cookies: {}, ip: `198.18.${block}.${(index % ADDRESS_BLOCK) + 1}` };
}

export function headersOf(session, extra = {}) {
  return {
    Origin: origin,
    "Content-Type": "application/json",
    "X-Turnstile-Token": "load-fake-pass",
    "X-Forwarded-For": session.ip,
    "X-CSRF-Token": session.cookies.mo_csrf || "",
    Cookie: Object.entries(session.cookies)
      .map(([name, value]) => `${name}=${value}`)
      .join("; "),
    ...extra,
  };
}

export function remember(session, response) {
  for (const [name, values] of Object.entries(response.cookies)) {
    const value = values[0] ? values[0].value : "";
    if (value === "") Reflect.deleteProperty(session.cookies, name);
    else session.cookies[name] = value;
  }
}

export function send(session, method, path, body, options = {}) {
  const response = http.request(
    method,
    api + path,
    body === undefined ? null : JSON.stringify(body),
    {
      headers: headersOf(session, options.headers),
      redirects: 0,
      timeout: options.timeout,
      tags: { name: options.name || path },
    },
  );
  remember(session, response);
  return response;
}

function verificationCode(session, email) {
  for (let attempt = 0; attempt < INBOX_ATTEMPTS; attempt += 1) {
    const inbox = send(session, "GET", `/v1/_test/inbox/${encodeURIComponent(email)}`, undefined, {
      name: "seed inbox",
    });
    const messages = inbox.status === 200 ? inbox.json("messages") : [];
    const message = messages.find((item) => item.template === "verify_contact" && item.code);
    if (message) return message.code;
    sleep(INBOX_PAUSE_SECONDS);
  }
  throw new Error(
    `No verification code reached the fake inbox of ${email}; run the stack with a default worker.`,
  );
}

function fund(session, runId, index) {
  const order = send(
    session,
    "POST",
    "/v1/billing/orders",
    { productCode: "pack_creator" },
    { name: "seed order", headers: { "Idempotency-Key": `seed-order-${runId}-${index}` } },
  );
  if (order.status !== 201)
    throw new Error(`Creating the seed order failed with ${order.status}: ${order.body}`);
  const razorpayOrderId = order.json("razorpayOrderId");
  const paid = send(
    session,
    "POST",
    `/v1/_test/razorpay/orders/${razorpayOrderId}/pay`,
    { outcome: "success", webhooks: [] },
    { name: "seed payment" },
  );
  if (paid.status !== 200)
    throw new Error(`The fake payment failed with ${paid.status}: ${paid.body}`);
  const verified = send(
    session,
    "POST",
    "/v1/billing/payments/verify",
    {
      razorpayOrderId,
      razorpayPaymentId: paid.json("razorpay_payment_id"),
      razorpaySignature: paid.json("razorpay_signature") || "",
    },
    { name: "seed verification", headers: { "Idempotency-Key": `seed-verify-${runId}-${index}` } },
  );
  if (verified.status !== 200 || !(verified.json("creditsGranted") > 0)) {
    throw new Error(`Settling the seed payment failed with ${verified.status}: ${verified.body}`);
  }
}

export function provisionAccount(runId, index) {
  const session = newSession(index);
  const email = `load-${runId}-${index}@example.com`;
  const password = `Load-${runId}-${index}-${Math.random().toString(36).slice(2)}Aa1!`;
  const registered = send(
    session,
    "POST",
    "/v1/auth/register",
    {
      name: "Load account",
      email,
      password,
    },
    { name: "seed register" },
  );
  if (registered.status !== 202)
    throw new Error(`Registration failed with ${registered.status}: ${registered.body}`);
  const verified = send(
    session,
    "POST",
    "/v1/auth/verify",
    { code: verificationCode(session, email) },
    {
      name: "seed verify",
    },
  );
  if (verified.status !== 200)
    throw new Error(`Verification failed with ${verified.status}: ${verified.body}`);
  fund(session, runId, index);
  return { identifier: email, password, index, session };
}

export function signIn(account) {
  const session = newSession(account.index);
  const login = send(
    session,
    "POST",
    "/v1/auth/login",
    {
      identifier: account.identifier,
      password: account.password,
    },
    { name: "login" },
  );
  const signedIn = check(login, {
    "password login succeeds": (response) => response.status === 200,
  });
  return signedIn ? session : null;
}
