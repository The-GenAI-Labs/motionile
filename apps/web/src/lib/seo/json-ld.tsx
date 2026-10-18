import { siteConfig } from "@/config/site";
import { absoluteUrl } from "@/lib/seo/metadata";
import { paiseToDecimalString } from "@/lib/utils/format";

export const SCHEMA_CONTEXT = "https://schema.org";

interface JsonLdBase {
  "@context": typeof SCHEMA_CONTEXT;
}

export interface OrganizationJsonLd extends JsonLdBase {
  "@type": "Organization";
  name: string;
  url: string;
  logo: string;
  description: string;
  email: string;
  sameAs: string[];
}

export interface SoftwareApplicationJsonLd extends JsonLdBase {
  "@type": "SoftwareApplication";
  name: string;
  url: string;
  description: string;
  applicationCategory: string;
  operatingSystem: string;
  publisher: { "@type": "Organization"; name: string; url: string };
}

export interface BreadcrumbItem {
  name: string;
  path: string;
}

export interface BreadcrumbListJsonLd extends JsonLdBase {
  "@type": "BreadcrumbList";
  itemListElement: {
    "@type": "ListItem";
    position: number;
    name: string;
    item: string;
  }[];
}

export interface VideoObjectInput {
  name: string;
  description: string;
  path: string;
  thumbnailUrls: readonly string[];
  uploadDate: Date | string;
  durationSeconds: number;
  contentUrl?: string;
  embedUrl?: string;
}

export interface VideoObjectJsonLd extends JsonLdBase {
  "@type": "VideoObject";
  name: string;
  description: string;
  url: string;
  thumbnailUrl: string[];
  uploadDate: string;
  duration: string;
  contentUrl?: string;
  embedUrl?: string;
  publisher: { "@type": "Organization"; name: string; url: string };
}

export interface ProductJsonLdInput {
  code: string;
  name: string;
  description: string | null;
  pricePaise: number;
  currency: string;
  path: string;
}

export interface OfferJsonLd {
  "@type": "Offer";
  price: string;
  priceCurrency: string;
  availability: "https://schema.org/InStock";
  url: string;
  priceSpecification: {
    "@type": "PriceSpecification";
    price: string;
    priceCurrency: string;
    valueAddedTaxIncluded: true;
  };
}

export interface ProductJsonLd extends JsonLdBase {
  "@type": "Product";
  name: string;
  description: string;
  sku: string;
  url: string;
  brand: { "@type": "Brand"; name: string };
  offers: OfferJsonLd;
}

export type JsonLdDocument =
  | OrganizationJsonLd
  | SoftwareApplicationJsonLd
  | BreadcrumbListJsonLd
  | VideoObjectJsonLd
  | ProductJsonLd;

const UNSAFE_JSON_CHARACTERS: Readonly<Record<string, string>> = {
  "<": "\\u003c",
  ">": "\\u003e",
  "&": "\\u0026",
  "\u2028": "\\u2028",
  "\u2029": "\\u2029",
};

export const serializeJsonLd = (data: JsonLdDocument | readonly JsonLdDocument[]): string =>
  JSON.stringify(data).replace(
    /[<>&\u2028\u2029]/g,
    (character) => UNSAFE_JSON_CHARACTERS[character] ?? character,
  );

export const toIsoDuration = (totalSeconds: number): string => {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  const hoursPart = hours > 0 ? `${hours}H` : "";
  const minutesPart = minutes > 0 ? `${minutes}M` : "";
  const secondsPart = remainder > 0 || seconds === 0 ? `${remainder}S` : "";
  return `PT${hoursPart}${minutesPart}${secondsPart}`;
};

const publisher = () =>
  ({ "@type": "Organization", name: siteConfig.name, url: absoluteUrl("/") }) as const;

export const buildOrganizationJsonLd = (): OrganizationJsonLd => ({
  "@context": SCHEMA_CONTEXT,
  "@type": "Organization",
  name: siteConfig.name,
  url: absoluteUrl("/"),
  logo: absoluteUrl("/icon"),
  description: siteConfig.description,
  email: siteConfig.contact.supportEmail,
  sameAs: Object.values(siteConfig.social),
});

export const buildSoftwareApplicationJsonLd = (): SoftwareApplicationJsonLd => ({
  "@context": SCHEMA_CONTEXT,
  "@type": "SoftwareApplication",
  name: siteConfig.name,
  url: absoluteUrl("/"),
  description: siteConfig.description,
  applicationCategory: "MultimediaApplication",
  operatingSystem: "Web",
  publisher: publisher(),
});

export const buildBreadcrumbListJsonLd = (
  items: readonly BreadcrumbItem[],
): BreadcrumbListJsonLd => ({
  "@context": SCHEMA_CONTEXT,
  "@type": "BreadcrumbList",
  itemListElement: items.map((item, index) => ({
    "@type": "ListItem",
    position: index + 1,
    name: item.name,
    item: absoluteUrl(item.path),
  })),
});

export const buildVideoObjectJsonLd = (video: VideoObjectInput): VideoObjectJsonLd => ({
  "@context": SCHEMA_CONTEXT,
  "@type": "VideoObject",
  name: video.name,
  description: video.description,
  url: absoluteUrl(video.path),
  thumbnailUrl: video.thumbnailUrls.map(absoluteUrl),
  uploadDate:
    typeof video.uploadDate === "string" ? video.uploadDate : video.uploadDate.toISOString(),
  duration: toIsoDuration(video.durationSeconds),
  ...(video.contentUrl === undefined ? {} : { contentUrl: absoluteUrl(video.contentUrl) }),
  ...(video.embedUrl === undefined ? {} : { embedUrl: absoluteUrl(video.embedUrl) }),
  publisher: publisher(),
});

export const buildProductJsonLd = (product: ProductJsonLdInput): ProductJsonLd => {
  const price = paiseToDecimalString(product.pricePaise);
  const url = absoluteUrl(product.path);
  return {
    "@context": SCHEMA_CONTEXT,
    "@type": "Product",
    name: product.name,
    description: product.description ?? `${product.name} from ${siteConfig.name}`,
    sku: product.code,
    url,
    brand: { "@type": "Brand", name: siteConfig.name },
    offers: {
      "@type": "Offer",
      price,
      priceCurrency: product.currency,
      availability: "https://schema.org/InStock",
      url,
      priceSpecification: {
        "@type": "PriceSpecification",
        price,
        priceCurrency: product.currency,
        valueAddedTaxIncluded: true,
      },
    },
  };
};

interface JsonLdProps {
  data: JsonLdDocument | readonly JsonLdDocument[];
}

export function JsonLd({ data }: JsonLdProps) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}
