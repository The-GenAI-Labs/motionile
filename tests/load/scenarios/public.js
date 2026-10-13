import { check, sleep } from "k6";
import http from "k6/http";

import { smokeThresholds } from "../thresholds.js";

const webBaseUrl = __ENV.WEB_BASE_URL || "http://localhost:3000";
const publicPaths = ["/", "/about", "/pricing", "/contact"];

export const options = {
  vus: 5,
  duration: "30s",
  thresholds: smokeThresholds,
};

export default function browsePublicPages() {
  for (const path of publicPaths) {
    const response = http.get(`${webBaseUrl}${path}`);
    check(response, {
      "status is 200": (result) => result.status === 200,
      "is html": (result) => (result.headers["Content-Type"] || "").includes("text/html"),
      "names the product": (result) => (result.body || "").includes("Motionile"),
    });
    sleep(0.2);
  }
}
