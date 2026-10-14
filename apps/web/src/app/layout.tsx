import "./globals.css";

import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Providers } from "@/app/providers";
import { siteConfig } from "@/config/site";
import { buildMetadata, TITLE_TEMPLATE } from "@/lib/seo/metadata";

const defaultMetadata = buildMetadata({ description: siteConfig.description, path: "/" });

export const metadata: Metadata = {
  ...defaultMetadata,
  metadataBase: new URL(siteConfig.url),
  title: {
    default: siteConfig.title,
    template: TITLE_TEMPLATE,
  },
  applicationName: siteConfig.name,
};

export const viewport: Viewport = {
  themeColor: siteConfig.themeColor,
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
