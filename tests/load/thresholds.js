export const smokeThresholds = {
  http_req_duration: ["p(95)<300"],
  http_req_failed: ["rate<0.01"],
  checks: ["rate>0.99"],
};

const profiles = {
  smoke: { vus: 5, duration: "30s" },
  full: {
    stages: [
      { duration: "2m", target: 25 },
      { duration: "5m", target: 50 },
      { duration: "2m", target: 0 },
    ],
  },
};

export function loadOptions() {
  const name = __ENV.LOAD_PROFILE || "smoke";
  const profile = profiles[name];
  if (!profile) {
    throw new Error(`Unknown LOAD_PROFILE ${name}; use one of ${Object.keys(profiles).join(", ")}`);
  }
  return { ...profile, thresholds: smokeThresholds };
}
