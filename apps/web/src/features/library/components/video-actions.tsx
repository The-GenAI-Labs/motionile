import { PencilIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { DeleteVideoDialog } from "@/features/library/components/delete-video-dialog";
import { ShareLinkDialog } from "@/features/library/components/share-link-dialog";
import { jobPath } from "@/features/library/schemas/library.schema";
import type { LibraryItem } from "@/features/library/types/library.types";

export function VideoActions({ item }: { item: LibraryItem }) {
  return (
    <div className="flex flex-wrap gap-2">
      <ShareLinkDialog item={item} />
      <Button asChild variant="outline" size="sm">
        <Link href={jobPath(item.jobId)} aria-label={`Revise ${item.title}`}>
          <PencilIcon aria-hidden="true" /> Revise
        </Link>
      </Button>
      <DeleteVideoDialog item={item} />
    </div>
  );
}
