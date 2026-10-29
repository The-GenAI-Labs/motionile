"use client";

import { useSyncExternalStore } from "react";

export const GRID_BREAKPOINTS = [
  { minWidth: 1280, columns: 4 },
  { minWidth: 960, columns: 3 },
  { minWidth: 600, columns: 2 },
] as const;

export const columnsForWidth = (width: number): number =>
  GRID_BREAKPOINTS.find((breakpoint) => width >= breakpoint.minWidth)?.columns ?? 1;

const subscribeToResize =
  (element: HTMLElement | null) =>
  (onChange: () => void): (() => void) => {
    if (element === null) {
      return () => undefined;
    }
    const observer = new ResizeObserver(onChange);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  };

export const useColumnCount = (element: HTMLElement | null): number =>
  useSyncExternalStore(
    subscribeToResize(element),
    () => columnsForWidth(element?.offsetWidth ?? 0),
    () => 1,
  );
