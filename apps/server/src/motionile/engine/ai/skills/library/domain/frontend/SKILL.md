---
name: frontend
description: Explaining how web interfaces work in the browser - HTML, CSS box model and layout, JavaScript event loop and DOM, the rendering pipeline (parse, style, layout, paint, composite), React-style components, state and re-rendering, hydration, server-side versus client-side rendering, web performance and Core Web Vitals, accessibility and responsive design. Use for what runs in the user's browser and how pages are built and rendered, not for server logic, databases or deployment.
metadata:
  layer: domain
---

# Frontend development

## When to use

Topics about what the user sees and touches in a browser: layout, styling, interactivity, component models, rendering strategies, performance, accessibility. Audience: beginners learning the web platform, and developers who use a framework without a model of what it does. Language and framework versions change quickly: say which version a behavior belongs to, or speak about the platform (DOM, CSS) instead.

## Structure

1. Show the problem as the user experiences it (a janky scroll, a blank page, a button that does nothing yet).
2. Name the browser mechanism responsible, in pipeline order: HTML parsed to the DOM, CSS to the CSSOM, combined into a render tree, then layout, paint, composite.
3. Show a minimal change and trace what the browser recomputes.
4. Contrast with the common wrong model.
5. End with the one rule of thumb the viewer keeps.

For framework topics, explain the idea first (UI as a function of state), then the mechanism (render, compare, commit), then the cost.

## Analogies and where they break

- DOM as a family tree of elements. Breaks: it is a live object model the page can mutate, not a static diagram.
- Box model as a framed picture: content, padding (mat), border (frame), margin (wall space). Breaks: margins can collapse between siblings.
- Component as a reusable stamp. Breaks: each use has its own state.
- Virtual DOM as an architect's draft compared with the building. Breaks: it is not inherently faster than careful direct updates; its value is a declarative programming model.
- Event loop as one cashier with a queue. Breaks: the browser also has separate queues and priorities for microtasks and rendering.
- Hydration as attaching wiring to a pre-built room. Breaks: the page is visible before it is interactive, which is the whole trade-off.

## Misconceptions to preempt

- "Re-render means the DOM updates." A component re-renders by running again; the DOM is changed only where the result differs.
- "JavaScript is multi-threaded." Page script runs on one main thread; workers are separate.
- "CSS animations are all cheap." Animating transform and opacity can be composited without layout; animating width or top forces layout.
- "SSR is always faster." It improves first content but adds server work and a gap before interactivity.
- "display: none and visibility: hidden are the same." One removes the box from layout; the other keeps its space.
- "Accessibility is an add-on." Semantic HTML gives keyboard and screen-reader behavior for free; div-and-click-handler loses it.
- "Responsive means shrinking." It means layout that adapts to available space.

## Terminology

Say element, attribute, DOM, selector, specificity, cascade, flexbox, grid, viewport, media query, container query, event bubbling versus capturing, component, props, state, effect, render, commit, hydration, SSR, SSG, ISR, CSR, bundle, code splitting, lazy loading. Core Web Vitals: LCP (loading), INP (interaction responsiveness, which replaced FID in March 2024), CLS (layout shift); say the metric names exactly and state the year if thresholds matter. Say "semantic HTML", not "clean HTML". Avoid "the virtual DOM is the reason React is fast".

## Visual pairings

- flow-diagram: the rendering pipeline, event loop turn, SSR then hydration.
- code-walkthrough: small HTML or CSS snippet, a component and its state.
- data-structure-operations: DOM tree insertion and removal, a list diff by key.
- comparison-split: CSR versus SSR versus SSG, flexbox versus grid, a blocking versus deferred script.
- timeline-sequence: page load waterfall, first paint to interactive.
- data-chart-story: before and after a performance fix.
- concept-metaphor: specificity, stacking context, the cascade.

## Accuracy checks

- Specificity order: inline styles, then ids, then classes, attributes and pseudo-classes, then elements; ties go to the later rule.
- Layout is geometry; paint is pixels; composite is layer assembly. Do not use them interchangeably.
- Keys in a list identify items across renders; they are not for the framework's benefit only.
- Frame budget at 60 frames per second is about 16.7 milliseconds.
- Say which APIs are universal browser features and which belong to a framework or library; give the version for the latter.
- Colors in any shown UI must meet contrast 4.5:1 for body text when the video teaches accessibility.

## Do

- Show the visual result next to the code that produces it.
- Use one small UI (a card, a counter, a list) across the whole video.
- Name the cost of every technique.

## Don't

- Don't rank frameworks or say one is dead.
- Don't present pixel values as universal; layouts depend on the viewport.
- Don't use a div where the example should teach a semantic element.
