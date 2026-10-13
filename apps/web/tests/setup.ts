import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
});

vi.mock("geist/font/sans", () => ({ GeistSans: { variable: "font-geist-sans" } }));
vi.mock("geist/font/mono", () => ({ GeistMono: { variable: "font-geist-mono" } }));
