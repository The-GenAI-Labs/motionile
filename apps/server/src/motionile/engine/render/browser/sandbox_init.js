(() => {
  "use strict";

  const config = window.__motionileConfig;
  delete window.__motionileConfig;

  const MAX_VIOLATIONS = 50;
  const SMIL_SELECTOR = "animate, animateTransform, animateMotion, set";
  const realRequestAnimationFrame = window.requestAnimationFrame.bind(window);
  const violations = [];
  const hardeningFailures = [];

  const record = (kind, detail) => {
    if (violations.length < MAX_VIOLATIONS) {
      violations.push(`${kind}: ${String(detail).slice(0, 200)}`);
    }
  };

  const refuse = (label, argument) => {
    record("api", argument === undefined ? label : `${label} ${argument}`);
    throw new TypeError(`${label} is not available in the render sandbox`);
  };

  const defineRefusal = (owner, name, label, asConstructor) => {
    if (!owner) {
      return;
    }
    const value = asConstructor
      ? function refusedConstructor(...args) {
          return refuse(label, args[0]);
        }
      : function refusedFunction(...args) {
          return refuse(label, args[0]);
        };
    try {
      Object.defineProperty(owner, name, { value, configurable: false, writable: false });
    } catch {
      hardeningFailures.push(label);
    }
  };

  const defineRefusingAccessor = (owner, name, label) => {
    if (!owner) {
      return;
    }
    try {
      Object.defineProperty(owner, name, {
        get: () => refuse(label),
        set: () => {
          refuse(label);
        },
        configurable: false,
      });
    } catch {
      hardeningFailures.push(label);
    }
  };

  const seededRandom = (seed) => {
    let state = seed >>> 0;
    return () => {
      state = (state + 0x6d2b79f5) >>> 0;
      let mixed = state;
      mixed = Math.imul(mixed ^ (mixed >>> 15), mixed | 1);
      mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
      return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
    };
  };

  const applyAspect = () => {
    const root = document.documentElement;
    if (root) {
      root.dataset.aspect = config.aspect;
      return true;
    }
    return false;
  };

  if (!applyAspect()) {
    const observer = new MutationObserver(() => {
      if (applyAspect()) {
        observer.disconnect();
      }
    });
    observer.observe(document, { childList: true });
  }

  const deepFreeze = (value) => {
    if (value && typeof value === "object") {
      Object.values(value).forEach(deepFreeze);
      Object.freeze(value);
    }
    return value;
  };

  Object.defineProperty(window, "__narration", {
    value: deepFreeze(config.narration),
    configurable: false,
    writable: false,
    enumerable: true,
  });

  Object.defineProperty(Math, "random", {
    value: seededRandom(config.seed),
    configurable: false,
    writable: false,
  });

  document.addEventListener(
    "securitypolicyviolation",
    (event) => record("csp", `${event.violatedDirective} ${event.blockedURI}`),
    true,
  );

  [
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "Worker",
    "SharedWorker",
    "BroadcastChannel",
  ].forEach((name) => defineRefusal(window, name, name, true));
  [
    "RTCPeerConnection",
    "webkitRTCPeerConnection",
    "RTCDataChannel",
    "RTCSessionDescription",
    "WebTransport",
    "Notification",
  ].forEach((name) => defineRefusal(window, name, name, true));
  defineRefusal(window, "fetch", "fetch", false);
  defineRefusal(window, "open", "window.open", false);
  defineRefusal(window, "importScripts", "importScripts", false);
  defineRefusal(navigator, "sendBeacon", "navigator.sendBeacon", false);
  ["serviceWorker", "geolocation", "mediaDevices", "clipboard", "credentials", "storage"].forEach(
    (name) => defineRefusingAccessor(Navigator.prototype, name, `navigator.${name}`),
  );
  ["localStorage", "sessionStorage", "indexedDB", "caches", "cookieStore"].forEach((name) =>
    defineRefusingAccessor(window, name, name),
  );
  defineRefusingAccessor(Document.prototype, "cookie", "document.cookie");

  const seekAnimations = (timeMs) => {
    for (const animation of document.getAnimations()) {
      animation.pause();
      animation.currentTime = timeMs;
    }
  };

  const seekMarkup = (timeMs) => {
    if (document.querySelector(SMIL_SELECTOR) === null) {
      return;
    }
    for (const svg of document.querySelectorAll("svg")) {
      svg.pauseAnimations();
      svg.setCurrentTime(timeMs / 1000);
    }
  };

  const seek = (timeMs) => {
    const timeline = window.__timeline;
    if (timeline && typeof timeline.time === "function") {
      timeline.time(timeMs / 1000, false);
    }
    seekAnimations(timeMs);
    seekMarkup(timeMs);
    return violations.length;
  };

  const nextFrame = () => new Promise((resolve) => realRequestAnimationFrame(() => resolve()));

  const settle = async (frames) => {
    for (let index = 0; index < frames; index += 1) {
      await nextFrame();
    }
    return violations.slice();
  };

  const awaitReady = async () => {
    if (!window.__ready) {
      return false;
    }
    await window.__ready;
    return true;
  };

  const readComposition = () => {
    const composition = window.__composition;
    const timeline = window.__timeline;
    if (!composition || !timeline || typeof timeline.duration !== "function") {
      return null;
    }
    return {
      composition: JSON.parse(JSON.stringify(composition)),
      timelineDurationMs: Math.round(timeline.duration() * 1000),
      sceneElements: Array.from(document.querySelectorAll("[data-scene]")).map(
        (element) => element.dataset.scene,
      ),
    };
  };

  Object.defineProperty(window, "__motionileSandbox", {
    value: Object.freeze({
      seek,
      settle,
      awaitReady,
      readComposition,
      violations: () => violations.slice(),
      hardeningFailures: () => hardeningFailures.slice(),
    }),
    configurable: false,
    writable: false,
  });
})();
