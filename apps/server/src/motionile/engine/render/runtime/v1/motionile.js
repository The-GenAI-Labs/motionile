(() => {
  "use strict";

  const VERSION = 1;
  const ACTIVE_ATTRIBUTE = "data-mo-active";
  const ASPECTS = Object.freeze({
    "16:9": { width: 1920, height: 1080, safe: { left: 96, right: 96, top: 64, bottom: 160 } },
    "9:16": { width: 1080, height: 1920, safe: { left: 72, right: 72, top: 160, bottom: 420 } },
    "1:1": { width: 1080, height: 1080, safe: { left: 72, right: 72, top: 72, bottom: 200 } },
  });
  const PLUGIN_NAMES = [
    "TextPlugin",
    "SplitText",
    "DrawSVGPlugin",
    "MorphSVGPlugin",
    "MotionPathPlugin",
    "CustomEase",
  ];
  const EDGE_PUNCTUATION = /^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu;

  let called = false;

  const normalizeWord = (text) => String(text).toLowerCase().replace(EDGE_PUNCTUATION, "");

  const requireGsap = () => {
    const gsap = window.gsap;
    if (!gsap || typeof gsap.timeline !== "function") {
      throw new Error("GSAP is not loaded; add the runtime gsap script before motionile.js");
    }
    PLUGIN_NAMES.forEach((name) => {
      if (window[name]) {
        gsap.registerPlugin(window[name]);
      }
    });
    return gsap;
  };

  const readNarration = () => {
    const narration = window.__narration;
    if (!narration || narration.version !== VERSION || !Array.isArray(narration.scenes)) {
      throw new Error("window.__narration is missing or has an unsupported version");
    }
    return narration;
  };

  const readAspect = () => {
    const aspect = document.documentElement.dataset.aspect;
    if (!Object.hasOwn(ASPECTS, aspect)) {
      throw new Error(`Unknown aspect "${aspect}" on <html data-aspect>`);
    }
    return aspect;
  };

  const validateConfig = (config) => {
    if (!config || typeof config !== "object") {
      throw new TypeError("Motionile.composition expects { scenes, aspects }");
    }
    if (!Array.isArray(config.aspects) || config.aspects.length === 0) {
      throw new TypeError("aspects must be a non-empty array");
    }
    config.aspects.forEach((aspect) => {
      if (!Object.hasOwn(ASPECTS, aspect)) {
        throw new TypeError(`Unsupported aspect "${aspect}"; use "16:9", "9:16" or "1:1"`);
      }
    });
    if (!Array.isArray(config.scenes) || config.scenes.length === 0) {
      throw new TypeError("scenes must be a non-empty array");
    }
    config.scenes.forEach((scene, index) => {
      if (!scene || typeof scene.id !== "string" || scene.id === "") {
        throw new TypeError(`scenes[${index}].id must be a non-empty string`);
      }
      if (typeof scene.build !== "function") {
        throw new TypeError(`scenes[${index}].build must be a function`);
      }
    });
  };

  const createWordLookup = (sceneId, words) => {
    const indexOf = (target, occurrence) => {
      if (typeof target === "number") {
        if (!Number.isInteger(target) || target < 0 || target >= words.length) {
          throw new RangeError(`Scene "${sceneId}" has no word at index ${target}`);
        }
        return target;
      }
      if (typeof target !== "string") {
        throw new TypeError("Word target must be an index or a string");
      }
      const needle = normalizeWord(target);
      let seen = 0;
      for (const word of words) {
        if (needle !== "" && normalizeWord(word.text) === needle) {
          if (seen === occurrence) {
            return word.index;
          }
          seen += 1;
        }
      }
      throw new Error(`Scene "${sceneId}" has no word matching "${target}" (match ${occurrence})`);
    };
    return {
      at: (target, occurrence = 0) => words[indexOf(target, occurrence)].start,
      end: (target, occurrence = 0) => words[indexOf(target, occurrence)].end,
    };
  };

  const createSceneContext = (entry, aspect, timeline) => {
    const { narrationScene, root, index } = entry;
    const spec = ASPECTS[aspect];
    const words = narrationScene.words.map((word, wordIndex) => ({
      index: wordIndex,
      text: word.text,
      start: word.sceneStartMs / 1000,
      end: word.sceneEndMs / 1000,
    }));
    const lookup = createWordLookup(narrationScene.id, words);
    return Object.freeze({
      id: narrationScene.id,
      index,
      root,
      duration: narrationScene.durationMs / 1000,
      text: narrationScene.text,
      words: Object.freeze(words),
      at: lookup.at,
      end: lookup.end,
      aspect,
      stage: Object.freeze({ width: spec.width, height: spec.height }),
      safeArea: Object.freeze({
        x: spec.safe.left,
        y: spec.safe.top,
        width: spec.width - spec.safe.left - spec.safe.right,
        height: spec.height - spec.safe.top - spec.safe.bottom,
      }),
      timeline,
    });
  };

  const collectEntries = (config, narration) => {
    const byId = new Map(narration.scenes.map((scene) => [scene.id, scene]));
    return config.scenes.map((scene, index) => {
      const narrationScene = byId.get(scene.id) ?? null;
      const root = document.querySelector(`[data-scene="${CSS.escape(scene.id)}"]`);
      return {
        scene,
        index,
        narrationScene,
        root,
        ready: narrationScene !== null && root !== null,
      };
    });
  };

  const activateScenes = (entries, timeMs) => {
    const lastIndex = entries.length - 1;
    entries.forEach((entry, position) => {
      if (!entry.ready) {
        return;
      }
      const { startMs, durationMs } = entry.narrationScene;
      const active = timeMs >= startMs && (timeMs < startMs + durationMs || position === lastIndex);
      entry.root.toggleAttribute(ACTIVE_ATTRIBUTE, active);
    });
  };

  const buildTimelines = async (gsap, config, narration, aspect) => {
    const entries = collectEntries(config, narration);
    const master = gsap.timeline({ paused: true });
    const scenes = [];
    for (const entry of entries) {
      if (!entry.ready) {
        scenes.push({ id: entry.scene.id, startMs: 0, endMs: 0, contentEndMs: 0 });
        continue;
      }
      const { startMs, durationMs } = entry.narrationScene;
      const child = gsap.timeline();
      await entry.scene.build(createSceneContext(entry, aspect, child));
      const contentSeconds = child.duration();
      if (contentSeconds < durationMs / 1000) {
        child.set({}, {}, durationMs / 1000);
      }
      master.add(child, startMs / 1000);
      scenes.push({
        id: entry.scene.id,
        startMs,
        endMs: startMs + durationMs,
        contentEndMs: Math.round(startMs + contentSeconds * 1000),
      });
    }
    const totalSeconds = narration.totalDurationMs / 1000;
    if (master.duration() < totalSeconds) {
      master.set({}, {}, totalSeconds);
    }
    master.eventCallback("onUpdate", () => activateScenes(entries, master.time() * 1000));
    activateScenes(entries, 0);
    return { master, entries, scenes };
  };

  const loadFonts = async () => {
    const faces = Array.from(document.fonts);
    await Promise.all(faces.map((face) => face.load().catch(() => face)));
    await document.fonts.ready;
    const failed = faces.filter((face) => face.status === "error");
    if (failed.length > 0) {
      throw new Error(`Fonts failed to load: ${failed.map((face) => face.family).join(", ")}`);
    }
  };

  const decodeImages = async () => {
    const images = Array.from(document.images);
    await Promise.all(
      images.map((image) =>
        image.decode().catch(() => {
          throw new Error(
            `Image failed to decode: ${image.id || image.alt || image.src.slice(0, 40)}`,
          );
        }),
      ),
    );
  };

  const holdAnimations = () => {
    for (const animation of document.getAnimations()) {
      animation.pause();
      animation.currentTime = 0;
    }
  };

  const run = async (config, aspect) => {
    const gsap = requireGsap();
    const narration = readNarration();
    await loadFonts();
    const { master, scenes } = await buildTimelines(gsap, config, narration, aspect);
    holdAnimations();
    window.__timeline = master;
    window.__composition = Object.freeze({
      version: VERSION,
      durationMs: Math.round(master.duration() * 1000),
      aspects: Object.freeze([...config.aspects]),
      scenes: Object.freeze(scenes.map((scene) => Object.freeze(scene))),
    });
    await decodeImages();
  };

  const composition = (config) => {
    if (called) {
      throw new Error("Motionile.composition can only be called once");
    }
    called = true;
    validateConfig(config);
    const aspect = readAspect();
    const ready = run(config, aspect);
    window.__ready = ready;
    ready.catch(() => undefined);
    return ready;
  };

  Object.defineProperty(window, "Motionile", {
    value: Object.freeze({ version: VERSION, composition }),
    enumerable: true,
  });
})();
