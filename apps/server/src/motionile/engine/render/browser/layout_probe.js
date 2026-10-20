(() => {
  "use strict";

  const SKIPPED_TAGS = new Set([
    "SCRIPT",
    "STYLE",
    "NOSCRIPT",
    "TEMPLATE",
    "TITLE",
    "HEAD",
    "META",
    "LINK",
  ]);
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });

  const toRgba = (css) => {
    context.clearRect(0, 0, 1, 1);
    context.fillStyle = "#000000";
    context.fillStyle = css;
    context.fillRect(0, 0, 1, 1);
    const data = context.getImageData(0, 0, 1, 1).data;
    return { r: data[0], g: data[1], b: data[2], a: data[3] / 255 };
  };

  const rectOf = (rect) => ({ x: rect.x, y: rect.y, width: rect.width, height: rect.height });

  const unionOf = (rects) => {
    if (rects.length === 0) {
      return null;
    }
    const left = Math.min(...rects.map((rect) => rect.left));
    const top = Math.min(...rects.map((rect) => rect.top));
    const right = Math.max(...rects.map((rect) => rect.right));
    const bottom = Math.max(...rects.map((rect) => rect.bottom));
    return { x: left, y: top, width: right - left, height: bottom - top };
  };

  const cssPath = (element) => {
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && current !== document.documentElement) {
      if (
        current.id &&
        document.querySelectorAll(`[id="${CSS.escape(current.id)}"]`).length === 1
      ) {
        parts.unshift(`#${CSS.escape(current.id)}`);
        break;
      }
      const tag = current.localName;
      const parent = current.parentElement;
      let part = tag;
      if (parent) {
        const same = Array.from(parent.children).filter((child) => child.localName === tag);
        if (same.length > 1) {
          part += `:nth-of-type(${same.indexOf(current) + 1})`;
        }
      }
      parts.unshift(part);
      current = parent;
    }
    return parts.join(" > ");
  };

  const effectiveOpacity = (element) => {
    let opacity = 1;
    for (let current = element; current; current = current.parentElement) {
      opacity *= Number.parseFloat(getComputedStyle(current).opacity);
    }
    return opacity;
  };

  const ownTextNodes = (element) =>
    Array.from(element.childNodes).filter(
      (node) => node.nodeType === Node.TEXT_NODE && node.nodeValue.trim() !== "",
    );

  const lineHeightOf = (style) => {
    const parsed = Number.parseFloat(style.lineHeight);
    return Number.isFinite(parsed) ? parsed : Number.parseFloat(style.fontSize) * 1.2;
  };

  const trimToLine = (rect, lineHeight) => {
    const trim = Math.max(0, rect.height - lineHeight) / 2;
    const top = rect.top + trim;
    const bottom = rect.bottom - trim;
    return {
      left: rect.left,
      right: rect.right,
      top,
      bottom,
      x: rect.left,
      y: top,
      width: rect.width,
      height: bottom - top,
    };
  };

  const textRects = (nodes, lineHeight) => {
    const rects = [];
    nodes.forEach((node) => {
      const range = document.createRange();
      range.selectNodeContents(node);
      Array.from(range.getClientRects()).forEach((rect) => {
        if (rect.width > 0 && rect.height > 0) {
          rects.push(trimToLine(rect, lineHeight));
        }
      });
    });
    return rects;
  };

  const scrollOverflow = (element, style) => {
    if (style.overflowX === "visible" && style.overflowY === "visible") {
      return { x: 0, y: 0 };
    }
    return {
      x: Math.max(0, element.scrollWidth - element.clientWidth),
      y: Math.max(0, element.scrollHeight - element.clientHeight),
    };
  };

  const describeText = (element, index) => {
    const nodes = ownTextNodes(element);
    const style = getComputedStyle(element);
    const lineRects = textRects(nodes, lineHeightOf(style));
    const box = unionOf(lineRects);
    if (box === null) {
      return null;
    }
    const isSvgText = element instanceof SVGElement;
    const fill = toRgba(isSvgText ? style.fill : style.webkitTextFillColor || style.color);
    const elementRect = element.getBoundingClientRect();
    const hasElementBox = elementRect.width > 0 && elementRect.height > 0;
    const scrolled = isSvgText ? { x: 0, y: 0 } : scrollOverflow(element, style);
    const overflowX = hasElementBox
      ? Math.max(
          0,
          box.x + box.width - (elementRect.x + elementRect.width),
          elementRect.x - box.x,
          scrolled.x,
        )
      : 0;
    const overflowY = hasElementBox
      ? Math.max(
          0,
          box.y + box.height - (elementRect.y + elementRect.height),
          elementRect.y - box.y,
          scrolled.y,
        )
      : 0;
    const clipText = (style.webkitBackgroundClip || style.backgroundClip) === "text";
    const visible = style.visibility === "visible" && Number.parseFloat(style.fontSize) > 0;
    return {
      index,
      selector: cssPath(element),
      scene: element.closest("[data-scene]")?.dataset.scene ?? null,
      rect: box,
      lineRects: lineRects.map(rectOf),
      elementRect: rectOf(elementRect),
      fontSizePx: Number.parseFloat(style.fontSize),
      fontWeight: Number.parseInt(style.fontWeight, 10) || 400,
      fill,
      clipText,
      opacity: effectiveOpacity(element),
      visible,
      overflowX,
      overflowY,
      important: element.hasAttribute("data-important"),
      text: nodes
        .map((node) => node.nodeValue.trim())
        .join(" ")
        .slice(0, 80),
    };
  };

  const describeImportant = (element, index) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      index,
      selector: cssPath(element),
      scene: element.closest("[data-scene]")?.dataset.scene ?? null,
      rect: rectOf(rect),
      opacity: effectiveOpacity(element),
      visible: style.visibility === "visible" && rect.width > 0 && rect.height > 0,
    };
  };

  const texts = [];
  const body = document.body;
  Array.from(body.querySelectorAll("*")).forEach((element) => {
    if (SKIPPED_TAGS.has(element.tagName.toUpperCase())) {
      return;
    }
    const described = describeText(element, texts.length);
    if (described !== null) {
      texts.push(described);
    }
  });

  const important = Array.from(document.querySelectorAll("[data-important]"))
    .filter((element) => ownTextNodes(element).length === 0)
    .map(describeImportant);

  return { texts, important };
})();
