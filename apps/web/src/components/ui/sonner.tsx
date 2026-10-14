"use client";

import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";
import type { CSSProperties } from "react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

const toasterStyle = {
  "--normal-bg": "var(--elevated)",
  "--normal-text": "var(--text)",
  "--normal-border": "var(--border)",
  "--border-radius": "var(--radius)",
} as CSSProperties;

export function Toaster(props: ToasterProps) {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      icons={{
        success: <CircleCheckIcon aria-hidden="true" className="size-4 text-success" />,
        info: <InfoIcon aria-hidden="true" className="size-4" />,
        warning: <TriangleAlertIcon aria-hidden="true" className="size-4" />,
        error: <OctagonXIcon aria-hidden="true" className="size-4 text-destructive" />,
        loading: <Loader2Icon aria-hidden="true" className="size-4 animate-spin" />,
      }}
      style={toasterStyle}
      {...props}
    />
  );
}
