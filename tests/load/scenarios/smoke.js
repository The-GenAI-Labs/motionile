import { check, sleep } from "k6";
import http from "k6/http";

import { smokeThresholds } from "../thresholds.js";

const apiBaseUrl = __ENV.API_BASE_URL || "http://localhost:8000";

export const options = {
  vus: 5,
  duration: "30s",
  thresholds: smokeThresholds,
};

export default function smoke() {
  const response = http.get(`${apiBaseUrl}/health/live`);
  check(response, {
    "status is 200": (result) => result.status === 200,
    "body reports ok": (result) => result.json("status") === "ok",
  });
  sleep(0.2);
}
