import { check, sleep } from "k6";
import http from "k6/http";

import { loadOptions } from "../thresholds.js";

const api = __ENV.API_BASE_URL || "http://localhost:8000";
const origin = __ENV.WEB_BASE_URL || "http://localhost:3000";
const accounts = JSON.parse(__ENV.AUTH_LOAD_ACCOUNTS || "[]");
export const options = { ...loadOptions(), noCookiesReset: true };
let signedIn = false;
let cookies = {};

function send(path, body) {
  const response = http.post(api + path, body ? JSON.stringify(body) : null, {
    headers: {
      Origin: origin,
      "Content-Type": "application/json",
      "X-Turnstile-Token": "load-fake-pass",
      "X-CSRF-Token": cookies.mo_csrf || "",
      Cookie: Object.entries(cookies)
        .map(([name, value]) => name + "=" + value)
        .join("; "),
    },
    redirects: 0,
    tags: { name: path },
  });
  for (const [name, values] of Object.entries(response.cookies)) {
    cookies[name] = values[0].value;
  }
  return response;
}

export function setup() {
  if (accounts.length < options.vus && !options.stages) {
    throw new Error("Supply one preverified account per VU in AUTH_LOAD_ACCOUNTS.");
  }
  if (options.stages && accounts.length < 50) {
    throw new Error("The full profile needs 50 preverified accounts.");
  }
  if (!accounts.length)
    throw new Error("AUTH_LOAD_ACCOUNTS is required; use local or CI with fake providers.");
}

export default function auth() {
  if (!signedIn) {
    const account = accounts[__VU - 1];
    const login = send("/v1/auth/login", {
      identifier: account.identifier,
      password: account.password,
    });
    signedIn = check(login, { "password login succeeds": (response) => response.status === 200 });
    sleep(3);
    return;
  }
  check(send("/v1/auth/refresh"), { "refresh succeeds": (response) => response.status === 204 });
  sleep(3);
}
