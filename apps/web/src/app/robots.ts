import type { MetadataRoute } from "next";

import { crawlerDisallowedPaths } from "@/config/navigation";
import { siteConfig } from "@/config/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: [...crawlerDisallowedPaths] }],
    sitemap: `${siteConfig.url}/sitemap.xml`,
    host: siteConfig.url,
  };
}
