---
name: terminal
description: Command-line look - near-black screen, phosphor green text with a single bright green accent, monospaced type everywhere, prompt prefixes, block cursor and stepped typing motion. Style for developer tooling, shell commands, Linux, git, DevOps, scripting, hacking and security topics, logs and code-centred explainers.
metadata:
  layer: style
  tokens: "--mo-bg: #070b07; --mo-surface: #0e160e; --mo-elevated: #162416; --mo-border: #2b4a2b; --mo-text-muted: #6fae6f; --mo-text-secondary: #9fd99f; --mo-text: #d4f7d4; --mo-accent: #39ff88; --mo-danger: #ff6b6b; --mo-success: #7be495"
---

# Terminal

## When to use

Commands, logs, code, pipelines, configuration and security walkthroughs, and anything a developer would read in a shell. Pairs well with `code-walkthrough`, `kinetic-typography` and `flow-diagram`. Avoid for soft, human or business topics.

## Structure

Palette: black-green `--mo-bg`, `--mo-surface` panels, pale green `--mo-text`, bright green `--mo-accent`. Contrast on `--mo-bg` and `--mo-surface`: text 15.8:1 or better, secondary 11.3:1, muted 7:1, accent 13.9:1, danger 6.6:1, success 11.7:1. The accent is a strong fill with `--mo-bg` text at 14.9:1.

## Do

- Type: Geist Mono for all text, titles weight 700 at `--mo-text-title`, body at `--mo-text-body`. Everything left-aligned; build text lines, not centred blocks.
- Prefix commands with `$ ` in `--mo-accent`, comments and output in `--mo-text-secondary`, hints in `--mo-text-muted`, errors in `--mo-danger`, passes in `--mo-success`.
- Windows: a `--mo-surface` panel with a 2 px `--mo-border`, radius `calc(var(--mo-unit) * 0.5)` and a one-line title bar in `--mo-text-muted`.
- Cursor: a solid block of `--mo-accent`, `0.6em` wide, placed after the last typed character; hide it with opacity at the end of a line.
- Motion: typing by revealing characters with `ease: "steps(n)"` where n is the character count (animate `width` of an overflow-hidden mono line in `ch` units), 0.5 to 1.2 s; panels cut in with a 0.15 s opacity step, no easing curves, no sliding.
- Highlight a line by lighting it with `--mo-accent` and giving it an `--mo-elevated` background bar.

## Don't

- Do not use proportional fonts, rounded corners above 8 px, glows or scanline overlays; effects hurt legibility and contrast checks.
- Do not use green for everything: reserve `--mo-accent` for the active item, prompts and the cursor.
- Do not wrap command lines; shorten them or split them across lines of at most 40 characters in portrait.
- Do not use `--mo-border` colour for text.

## runtime@1 patterns

```css
.mo-s-demo {
  font-family: var(--mo-font-mono);
}
.mo-s-demo .window {
  background: var(--mo-surface);
  border: 2px solid var(--mo-border);
  border-radius: calc(var(--mo-unit) * 0.5);
  padding: calc(var(--mo-unit) * 3);
  text-align: left;
}
.mo-s-demo .prompt::before {
  content: "$ ";
  color: var(--mo-accent);
}
.mo-s-demo .line {
  overflow: hidden;
  white-space: pre;
  width: 0;
}
.mo-s-demo .cursor {
  display: inline-block;
  width: 0.6em;
  height: 1.1em;
  background: var(--mo-accent);
  vertical-align: text-bottom;
}
```
