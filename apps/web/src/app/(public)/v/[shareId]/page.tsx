import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Button } from "@/components/ui/button";
import { siteConfig } from "@/config/site";
import { loadSharedVideo } from "@/features/library/api/share.server.api";
import { SharedVideoPlayer } from "@/features/library/components/shared-video-player";
import { buildVideoObjectJsonLd, JsonLd } from "@/lib/seo/json-ld";
import { buildMetadata, OPEN_GRAPH_IMAGE_ALT } from "@/lib/seo/metadata";
import { buildVideoMetadata } from "@/lib/seo/video-metadata";

export const dynamic = "force-dynamic";

const VIDEO_MIME_TYPE = "video/mp4";

interface SharePageProps {
  params: Promise<{ shareId: string }>;
}

const sharePath = (shareId: string): string => `/v/${shareId}`;

export async function generateMetadata({ params }: SharePageProps): Promise<Metadata> {
  const { shareId } = await params;
  const video = await loadSharedVideo(shareId);
  if (video === null) {
    return buildMetadata({
      title: "Video not found",
      description: "This shared video does not exist or its link was turned off.",
      path: sharePath(shareId),
      noIndex: true,
    });
  }
  return buildVideoMetadata({
    title: video.title,
    description:
      video.summary ?? `${video.title}, an animated explainer video made with ${siteConfig.name}.`,
    path: sharePath(shareId),
    indexable: video.allowIndexing,
    video: {
      url: video.playbackUrl,
      type: VIDEO_MIME_TYPE,
      width: video.width,
      height: video.height,
    },
    ...(video.posterUrl
      ? {
          poster: {
            url: video.posterUrl,
            width: video.width,
            height: video.height,
            alt: `${video.title}. ${OPEN_GRAPH_IMAGE_ALT}`,
          },
        }
      : {}),
  });
}

export default async function SharedVideoPage({ params }: SharePageProps) {
  const { shareId } = await params;
  const video = await loadSharedVideo(shareId);
  if (video === null) {
    notFound();
  }
  const description =
    video.summary ?? `${video.title}, an animated explainer video made with ${siteConfig.name}.`;
  return (
    <article className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-4 py-10 sm:px-6">
      {video.allowIndexing ? (
        <JsonLd
          data={buildVideoObjectJsonLd({
            name: video.title,
            description,
            path: sharePath(shareId),
            thumbnailUrls: [video.posterUrl ?? "/opengraph-image"],
            ...(video.durationMs === null ? {} : { durationSeconds: video.durationMs / 1000 }),
            contentUrl: video.playbackUrl,
            embedUrl: sharePath(shareId),
          })}
        />
      ) : null}
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{video.title}</h1>
        {video.summary ? <p className="text-subtle-foreground">{video.summary}</p> : null}
      </header>
      <SharedVideoPlayer slug={shareId} video={video} />
      <aside
        aria-labelledby="made-with-heading"
        className="flex flex-col gap-4 rounded-xl border bg-surface p-6 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="space-y-1">
          <h2 id="made-with-heading" className="font-semibold">
            Made with {siteConfig.name}
          </h2>
          <p className="text-sm text-muted-foreground">{siteConfig.tagline}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link href="/register">Create your own video</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/create">Open {siteConfig.name}</Link>
          </Button>
        </div>
      </aside>
    </article>
  );
}
