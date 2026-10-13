import type { Metadata } from "next";

import { siteConfig } from "@/config/site";

export const TITLE_TEMPLATE = `%s · ${siteConfig.name}`;

export const OPEN_GRAPH_IMAGE_SIZE = { width: 1200, height: 630 } as const;

export const OPEN_GRAPH_IMAGE_ALT = `${siteConfig.name}: ${siteConfig.tagline}`;

export interface SocialImage {
  url: string;
  width: number;
  height: number;
  alt: string;
}

export interface BuildMetadataOptions {
  title?: string;
  description: string;
  path: string;
  noIndex?: boolean;
  openGraphType?: "website" | "article" | "video.other";
  images?: readonly SocialImage[];
}

export const absoluteUrl = (path: string): string => {
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return normalizedPath === "/" ? `${siteConfig.url}/` : `${siteConfig.url}${normalizedPath}`;
};

export const formatTitle = (title: string): string => TITLE_TEMPLATE.replace("%s", title);

export const defaultSocialImage = (): SocialImage => ({
  url: absoluteUrl("/opengraph-image"),
  ...OPEN_GRAPH_IMAGE_SIZE,
  alt: OPEN_GRAPH_IMAGE_ALT,
});

export const buildMetadata = ({
  title,
  description,
  path,
  noIndex = false,
  openGraphType = "website",
  images,
}: BuildMetadataOptions): Metadata => {
  const canonical = absoluteUrl(path);
  const socialTitle = title === undefined ? siteConfig.title : formatTitle(title);
  const socialImages = (images ?? [defaultSocialImage()]).map((image) => ({
    ...image,
    url: absoluteUrl(image.url),
  }));
  return {
    title: title ?? { absolute: siteConfig.title },
    description,
    alternates: { canonical },
    openGraph: {
      type: openGraphType,
      siteName: siteConfig.name,
      locale: siteConfig.locale,
      url: canonical,
      title: socialTitle,
      description,
      images: socialImages,
    },
    twitter: {
      card: "summary_large_image",
      title: socialTitle,
      description,
      images: socialImages,
    },
    robots: noIndex ? { index: false, follow: false } : { index: true, follow: true },
  };
};
