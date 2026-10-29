import { VideoIcon } from "lucide-react";
import Image from "next/image";

export function LibraryThumbnail({ url }: { url: string | null }) {
  if (url === null) {
    return (
      <span className="grid size-full place-items-center bg-elevated text-muted-foreground">
        <VideoIcon aria-hidden="true" className="size-8" />
      </span>
    );
  }
  return (
    <Image
      src={url}
      alt=""
      fill
      unoptimized
      sizes="(min-width: 1280px) 25vw, (min-width: 960px) 33vw, (min-width: 600px) 50vw, 100vw"
      className="object-cover"
    />
  );
}
