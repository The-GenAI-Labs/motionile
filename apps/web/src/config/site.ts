import { env } from "@/config/env";

export const brandPalette = {
  background: "#0E0E10",
  surface: "#16161A",
  elevated: "#1E1E23",
  border: "#2A2A30",
  mutedText: "#8A8A93",
  secondaryText: "#B4B4BC",
  text: "#F2F2F3",
  accent: "#FAFAFA",
} as const;

export const siteConfig = {
  name: "Motionile",
  title: "Motionile — AI Animated Explainer Videos",
  tagline: "Turn any topic into a narrated, animated explainer video.",
  description:
    "Motionile turns a topic or a question into a short animated explainer video with narration, ready to publish in one click.",
  url: env.NEXT_PUBLIC_SITE_URL,
  locale: "en_IN",
  themeColor: brandPalette.background,
  contact: {
    supportEmail: "support@motionile.com",
    billingEmail: "billing@motionile.com",
    privacyEmail: "privacy@motionile.com",
    grievanceEmail: "grievance@motionile.com",
    legalEmail: "legal@motionile.com",
  },
  social: {
    youtube: "https://www.youtube.com/@motionile",
    linkedin: "https://www.linkedin.com/company/motionile",
    x: "https://x.com/motionile",
  },
  legal: {
    entityName: "[Legal entity name]",
    registeredAddress: "[Registered office address]",
    jurisdictionCity: "[City]",
    grievanceOfficerName: "[Grievance Officer name]",
    gstin: "[GSTIN]",
    effectiveDate: "[Effective date]",
    lastUpdated: "[Last updated date]",
  },
} as const;
