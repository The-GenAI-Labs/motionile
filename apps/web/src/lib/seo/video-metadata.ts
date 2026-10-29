import type { Metadata } from "next";

import { absoluteUrl, buildMetadata, type SocialImage } from "@/lib/seo/metadata";

export interface VideoMetadataInput {
  title: string;
  description: string;
  path: string;
  indexable: boolean;
  video: {
    url: string;
    type: string;
    width: number;
    height: number;
  };
  poster?: SocialImage;
}

export const buildVideoMetadata = ({
  title,
  description,
  path,
  indexable,
  video,
  poster,
}: VideoMetadataInput): Metadata => {
  const base = buildMetadata({
    title,
    description,
    path,
    noIndex: !indexable,
    openGraphType: "video.other",
    ...(poster ? { images: [poster] } : {}),
  });
  const pageUrl = absoluteUrl(path);
  return {
    ...base,
    openGraph: {
      ...base.openGraph,
      type: "video.other",
      videos: [
        {
          url: video.url,
          secureUrl: video.url,
          type: video.type,
          width: video.width,
          height: video.height,
        },
      ],
    },
    twitter: {
      title: base.twitter?.title ?? title,
      description,
      images: base.twitter?.images ?? [],
      card: "player",
      players: [
        { playerUrl: pageUrl, streamUrl: video.url, width: video.width, height: video.height },
      ],
    },
  };
};
