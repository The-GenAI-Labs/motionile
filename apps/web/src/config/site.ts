import { env } from "@/config/env";

export const siteConfig = {
  name: "Motionile",
  title: "Motionile — AI Animated Explainer Videos",
  tagline: "Turn any topic into a narrated, animated explainer video.",
  description:
    "Motionile turns a topic or a question into a short animated explainer video with narration, ready to publish in one click.",
  url: env.NEXT_PUBLIC_SITE_URL,
  themeColor: "#0E0E10",
} as const;
