"use client";

import { useRef } from "react";

import { recordShareView } from "@/features/library/api/library.api";

export const useRecordShareView = (slug: string): (() => void) => {
  const recorded = useRef(false);
  return () => {
    if (recorded.current) {
      return;
    }
    recorded.current = true;
    recordShareView(slug).catch(() => undefined);
  };
};
