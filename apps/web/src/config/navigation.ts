import {
  CreditCard,
  FolderTree,
  Gauge,
  History,
  LayoutDashboard,
  Library,
  type LucideIcon,
  PlusCircle,
  Receipt,
  Settings,
  Share2,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Users,
} from "lucide-react";
import type { MetadataRoute, Route } from "next";

export type AppPath = `/${string}`;

export interface PublicLink {
  title: string;
  href: Route;
}

export interface FooterLinkGroup {
  title: string;
  links: readonly PublicLink[];
}

export interface AppNavigationItem {
  title: string;
  href: AppPath;
  icon: LucideIcon;
  permission?: string;
}

export interface AppNavigationArea {
  label: string;
  homeHref: AppPath;
  items: readonly AppNavigationItem[];
}

export interface BillingLink {
  title: string;
  href: AppPath;
}

export interface AdminBillingLink {
  title: string;
  href: AppPath;
  permission: string;
}

export type AppArea = "user" | "admin";

export interface PublicPage {
  path: Route;
  changeFrequency: NonNullable<MetadataRoute.Sitemap[number]["changeFrequency"]>;
  priority: number;
}

export const legalLinks = [
  { title: "Terms of Service", href: "/legal/terms" },
  { title: "Privacy Policy", href: "/legal/privacy" },
  { title: "Refund and Cancellation Policy", href: "/legal/refund-policy" },
  { title: "Data Deletion", href: "/legal/data-deletion" },
] as const satisfies readonly PublicLink[];

export const publicNavigation = [
  { title: "Explore", href: "/explore" },
  { title: "Pricing", href: "/pricing" },
  { title: "About", href: "/about" },
  { title: "Contact", href: "/contact" },
] as const satisfies readonly PublicLink[];

export const footerNavigation = [
  {
    title: "Product",
    links: [
      { title: "Home", href: "/" },
      { title: "Explore", href: "/explore" },
      { title: "Pricing", href: "/pricing" },
    ],
  },
  {
    title: "Company",
    links: [
      { title: "About", href: "/about" },
      { title: "Contact", href: "/contact" },
    ],
  },
  { title: "Legal", links: legalLinks },
] as const satisfies readonly FooterLinkGroup[];

export const publicPages = [
  { path: "/", changeFrequency: "weekly", priority: 1 },
  { path: "/explore", changeFrequency: "weekly", priority: 0.9 },
  { path: "/pricing", changeFrequency: "monthly", priority: 0.8 },
  { path: "/about", changeFrequency: "monthly", priority: 0.6 },
  { path: "/contact", changeFrequency: "yearly", priority: 0.5 },
  { path: "/legal/terms", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/privacy", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/refund-policy", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/data-deletion", changeFrequency: "yearly", priority: 0.3 },
] as const satisfies readonly PublicPage[];

export const userNavigation = {
  label: "Workspace",
  homeHref: "/dashboard",
  items: [
    { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { title: "Create", href: "/create", icon: PlusCircle },
    { title: "Library", href: "/library", icon: Library },
    { title: "Publications", href: "/publications", icon: Share2 },
    { title: "Skills", href: "/skills", icon: Sparkles },
    { title: "Billing", href: "/billing", icon: CreditCard },
    { title: "Settings", href: "/settings/profile", icon: Settings },
  ],
} as const satisfies AppNavigationArea;

export const billingNavigation = [
  { title: "Overview", href: "/billing" },
  { title: "Plans", href: "/billing/plans" },
  { title: "Credits", href: "/billing/credits" },
  { title: "History", href: "/billing/history" },
] as const satisfies readonly BillingLink[];

export const adminBillingNavigation = [
  { title: "Overview", href: "/admin/billing", permission: "billing.read" },
  { title: "Products", href: "/admin/billing/products", permission: "billing.read" },
  { title: "Payments", href: "/admin/billing/payments", permission: "billing.read" },
  { title: "Orders", href: "/admin/billing/orders", permission: "billing.read" },
  { title: "Refunds", href: "/admin/billing/refunds", permission: "billing.read" },
  { title: "Subscriptions", href: "/admin/billing/subscriptions", permission: "billing.read" },
  { title: "Reconciliation", href: "/admin/billing/reconciliation", permission: "billing.read" },
  { title: "Webhooks", href: "/admin/billing/webhooks", permission: "billing.webhooks.manage" },
] as const satisfies readonly AdminBillingLink[];

export const adminNavigation = {
  label: "Admin",
  homeHref: "/admin",
  items: [
    { title: "Overview", href: "/admin", icon: Gauge, permission: "analytics.read" },
    { title: "Users", href: "/admin/users", icon: Users, permission: "users.read" },
    { title: "Roles", href: "/admin/roles", icon: Shield, permission: "roles.read" },
    { title: "Billing", href: "/admin/billing", icon: Receipt, permission: "billing.read" },
    { title: "Audit logs", href: "/admin/audit-logs", icon: History, permission: "audit.read" },
    { title: "Catalog", href: "/admin/catalog", icon: FolderTree, permission: "catalog.manage" },
    { title: "Feature flags", href: "/admin/flags", icon: Sparkles, permission: "flags.manage" },
    {
      title: "Settings",
      href: "/admin/settings",
      icon: SlidersHorizontal,
      permission: "settings.read",
    },
  ],
} as const satisfies AppNavigationArea;

export const appNavigation: Record<AppArea, AppNavigationArea> = {
  user: userNavigation,
  admin: adminNavigation,
};

export const userAreaPaths = [
  ...userNavigation.items.map((item) => item.href),
  "/jobs",
  "/publish",
] as const satisfies readonly AppPath[];

export const authPaths = [
  "/login",
  "/register",
  "/verify",
  "/forgot-password",
  "/reset-password",
  "/refresh",
] as const satisfies readonly AppPath[];

export const crawlerDisallowedPaths: readonly AppPath[] = [
  adminNavigation.homeHref,
  "/api/",
  "/settings",
  ...userAreaPaths,
  ...authPaths,
];

export const isActivePath = (pathname: string, href: AppPath, homeHref: AppPath): boolean => {
  if (href === homeHref) {
    return pathname === href;
  }
  return pathname === href || pathname.startsWith(`${href}/`);
};
