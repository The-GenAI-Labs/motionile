import type { Rendition } from "@/features/library/types/library.types";

const AMZ_DATE_PATTERN = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/;
const MS_PER_SECOND = 1_000;

const expiryFromAmzParameters = (params: URLSearchParams): number | null => {
  const signedAt = params.get("X-Amz-Date");
  const lifetime = Number(params.get("X-Amz-Expires"));
  const parts = signedAt === null ? null : AMZ_DATE_PATTERN.exec(signedAt);
  if (parts === null || !Number.isFinite(lifetime) || lifetime <= 0) {
    return null;
  }
  const [year, month, day, hour, minute, second] = parts.slice(1).map(Number) as [
    number,
    number,
    number,
    number,
    number,
    number,
  ];
  return Date.UTC(year, month - 1, day, hour, minute, second) + lifetime * MS_PER_SECOND;
};

const expiryFromEpochParameter = (params: URLSearchParams): number | null => {
  const seconds = Number(params.get("Expires"));
  return Number.isInteger(seconds) && seconds > 0 ? seconds * MS_PER_SECOND : null;
};

export const urlExpiryMs = (value: string | null | undefined): number | null => {
  if (!value || !URL.canParse(value)) {
    return null;
  }
  const params = new URL(value).searchParams;
  return expiryFromAmzParameters(params) ?? expiryFromEpochParameter(params);
};

export const renditionUrls = (rendition: Rendition): string[] =>
  [
    rendition.url,
    rendition.posterUrl,
    rendition.posterJpegUrl,
    rendition.subtitlesUrl,
    rendition.subtitlesSrtUrl,
  ].filter((value): value is string => typeof value === "string");

export const earliestExpiryMs = (renditions: readonly Rendition[]): number | null => {
  const expiries = renditions
    .flatMap(renditionUrls)
    .map(urlExpiryMs)
    .filter((value): value is number => value !== null);
  return expiries.length === 0 ? null : Math.min(...expiries);
};
