import { check, sleep } from "k6";
import http from "k6/http";

import { loadOptions } from "../thresholds.js";

const apiBaseUrl = __ENV.API_BASE_URL || "http://localhost:8000";
const webBaseUrl = __ENV.WEB_BASE_URL || "http://localhost:3000";

export const options = loadOptions();

function get(path, tags) {
  return http.get(path, { tags });
}

export function setup() {
  const response = get(`${apiBaseUrl}/v1/catalog/paths`, { name: "catalog paths" });
  check(response, {
    "catalog paths status is 200": (result) => result.status === 200,
    "catalog paths are JSON": (result) =>
      (result.headers["Content-Type"] || "").includes("application/json"),
  });
  const body = response.json();
  const records = Array.isArray(body) ? body : (body.items ?? body.paths ?? []);
  const paths = records
    .map((record) => (typeof record === "string" ? record : record.path))
    .filter((path) => typeof path === "string" && path.startsWith("/explore/"));
  const representatives = new Map();
  for (const path of paths) {
    const depth = path.split("/").filter(Boolean).length;
    if (!representatives.has(depth)) representatives.set(depth, path);
  }
  return ["/explore", ...representatives.values()];
}

export default function browseExplore(explorePaths) {
  const tree = get(`${apiBaseUrl}/v1/catalog/tree`, { name: "catalog tree" });
  check(tree, {
    "catalog tree status is 200": (result) => result.status === 200,
    "catalog tree is JSON": (result) =>
      (result.headers["Content-Type"] || "").includes("application/json"),
  });

  const search = get(`${apiBaseUrl}/v1/catalog/search?q=system`, {
    name: "catalog search",
  });
  check(search, {
    "catalog search status is 200": (result) => result.status === 200,
    "catalog search is JSON": (result) =>
      (result.headers["Content-Type"] || "").includes("application/json"),
  });

  for (const path of explorePaths) {
    const page = get(`${webBaseUrl}${path}`, { name: "explore page" });
    check(page, {
      "explore page status is 200": (result) => result.status === 200,
      "explore page is HTML": (result) =>
        (result.headers["Content-Type"] || "").includes("text/html"),
      "explore page names Motionile": (result) => (result.body || "").includes("Motionile"),
    });
    sleep(0.2);
  }
}
