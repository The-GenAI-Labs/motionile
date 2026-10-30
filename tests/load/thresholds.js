export const smokeThresholds = {
  http_req_duration: ["p(95)<300"],
  http_req_failed: ["rate<0.01"],
  checks: ["rate>0.99"],
};

export const jobsThresholds = {
  "http_req_duration{name:create job}": ["p(95)<500"],
  "http_req_duration{name:replay create job}": ["p(95)<400"],
  "http_req_duration{name:get job}": ["p(95)<300"],
  "http_req_duration{name:list jobs}": ["p(95)<300"],
  "http_req_duration{name:cancel job}": ["p(95)<500"],
  "http_req_duration{name:replay job events}": ["p(95)<1000"],
  stream_first_byte_ms: ["p(95)<1000"],
  stream_open_errors: ["rate<0.01"],
  job_flow_errors: ["rate<0.01"],
  job_rejections: ["rate<0.05"],
  checks: ["rate>0.99"],
};

const SMOKE_VIRTUAL_USERS = 5;
const FULL_PEAK_VIRTUAL_USERS = 50;

const profiles = {
  smoke: { vus: SMOKE_VIRTUAL_USERS, duration: "30s" },
  full: {
    stages: [
      { duration: "2m", target: 25 },
      { duration: "5m", target: FULL_PEAK_VIRTUAL_USERS },
      { duration: "2m", target: 0 },
    ],
  },
};

function selectedProfile() {
  const name = __ENV.LOAD_PROFILE || "smoke";
  const profile = profiles[name];
  if (!profile) {
    throw new Error(`Unknown LOAD_PROFILE ${name}; use one of ${Object.keys(profiles).join(", ")}`);
  }
  return profile;
}

export function loadOptions() {
  return { ...selectedProfile(), thresholds: smokeThresholds };
}

export function jobsLoadOptions() {
  return { ...selectedProfile(), thresholds: jobsThresholds, setupTimeout: "900s" };
}

export function peakVirtualUsers() {
  const profile = selectedProfile();
  return profile.stages ? FULL_PEAK_VIRTUAL_USERS : profile.vus;
}
