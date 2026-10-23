# 26. Render sandbox design

- Status: Accepted
- Date: 2026-10-19

## Context

Generated HTML is untrusted code that runs in a browser inside the worker. The worker holds database access, storage credentials and an instance role. A malicious or confused composition must not read them, reach the network, the cloud metadata service or other files, or exhaust the host. Static checks on HTML and JavaScript cannot be complete.

## Decision

Security comes from the sandbox. Static checks are an extra layer.

**Process**

- Playwright Chromium launched with its own sandbox enabled; `--no-sandbox` is never used.
- The worker container runs as a non-root user with Playwright's recommended seccomp profile and no added capabilities. Chromium gets `shm_size` for its renderer.
- A fresh browser context for every render, with no permissions, downloads, service workers, WebRTC, geolocation or notifications.
- Chromium starts with an explicit minimal environment (`PATH`, `HOME`, `LANG`, `TZ` and the Windows system variables) supplied through `RenderEngineConfig.browser_environment`; the worker's secrets are never inherited. A sandbox that cannot stop its browser within the shutdown timeout kills the processes that carry its own process marker and their descendants.
- Service workers are off through the opaque origin, `worker-src 'none'` and the init-script stub. Playwright's `service_workers="block"` is deliberately not used: it makes Playwright's injected script throw under the CSP `sandbox` header.

**Network**

- Every request is intercepted. Only the virtual runtime origin (answered from local files) and `data:` are fulfilled; everything else is aborted and recorded. The composition document itself is fulfilled by the renderer with a strict Content Security Policy header: `default-src 'none'`, scripts and styles from the runtime origin and inline, images and fonts from `data:` and the runtime origin, `connect-src 'none'`, `frame-src 'none'`, `worker-src 'none'`, `form-action 'none'`, `base-uri 'none'` and `sandbox allow-scripts`.
- Any attempted request, whether aborted by the interceptor or reported as a CSP violation, fails the render with `network_violation`. The browser also gets a host resolver rule that fails every name and a black-hole proxy, so a bypass of the interceptor still cannot leave the host.
- An init script removes network, storage, worker, navigation and WebRTC APIs; it is a second layer, not the control.

**Limits**

- Timeouts on page load, `__ready` and every per-frame evaluation. A hung page is killed and the render fails with `timeout`. Page errors and console errors fail the render with their messages in the report.
- The composition is limited to 1 MB of HTML, 2 MB of data URIs and 5,000 elements before it reaches the browser, and each stage has a wall-clock budget.

**Static layer**

- A spec-compliant HTML5 parser removes or rejects `iframe`, `frame`, `object`, `embed`, `form`, `base`, `meta http-equiv`, `audio`, `video`, non-runtime `link`, event-handler attributes, `javascript:` URLs, and any URL outside the runtime origin and `data:` images in `src`, `href`, `srcset`, `poster`, CSS `url()` and `@import`. A script screen flags network, eval, worker, storage and navigation APIs. Findings are returned to the generator for repair.

## Consequences

- A composition that tries to exfiltrate, navigate, embed or fetch fails safely with a stable error code and zero outbound requests; a test suite with one fixture per technique proves it.
- The runtime must ship all fonts and libraries locally; nothing loads from a CDN at render time.
- Rendering needs a Linux seccomp profile and non-root execution, which the Compose files and the worker Dockerfile target now set.
- The sandbox adds a few seconds of start-up per aspect and per capturing page.
