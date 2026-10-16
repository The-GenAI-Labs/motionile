"use client";

import { CameraIcon, Trash2Icon } from "lucide-react";
import { useEffect, useState } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const AVATAR_MAX_BYTES = 2 * 1024 * 1024;
const ACCEPTED_AVATAR_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

export const avatarFileError = (file: File): string | null => {
  if (file.size > AVATAR_MAX_BYTES) {
    return "Choose an image smaller than 2 MB.";
  }
  if (!ACCEPTED_AVATAR_TYPES.has(file.type)) {
    return "Choose a JPEG, PNG or WebP image.";
  }
  return null;
};

interface AvatarUploadProps {
  name: string | null;
  avatarUrl: string | null;
  uploading: boolean;
  onUpload: (file: File) => Promise<void>;
  onRemove: () => Promise<void>;
}

export function AvatarUpload({
  name,
  avatarUrl,
  uploading,
  onUpload,
  onRemove,
}: AvatarUploadProps) {
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(
    () => () => {
      if (preview !== null) URL.revokeObjectURL(preview);
    },
    [preview],
  );
  const chooseFile = (file: File | undefined) => {
    if (file === undefined) {
      return;
    }
    const message = avatarFileError(file);
    setError(message);
    if (message !== null) {
      return;
    }
    if (preview !== null) {
      URL.revokeObjectURL(preview);
    }
    setPreview(URL.createObjectURL(file));
    void onUpload(file);
  };
  return (
    <section aria-labelledby="avatar-heading" className="flex flex-wrap items-center gap-5">
      <Avatar className="size-20">
        <AvatarImage
          src={preview ?? avatarUrl ?? undefined}
          alt={name ? `${name}'s avatar` : "Your avatar"}
        />
        <AvatarFallback>{name?.slice(0, 2).toUpperCase() ?? "MO"}</AvatarFallback>
      </Avatar>
      <div className="space-y-2">
        <h2 id="avatar-heading" className="font-semibold">
          Profile image
        </h2>
        <div className="flex flex-wrap gap-2">
          <Label
            htmlFor="avatar-file"
            className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border bg-surface px-3 text-sm font-medium hover:bg-elevated focus-within:ring-[3px] focus-within:ring-ring"
          >
            <CameraIcon aria-hidden="true" className="size-4" />{" "}
            {uploading ? "Uploading…" : "Choose image"}
          </Label>
          <Input
            id="avatar-file"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            disabled={uploading}
            onChange={(event) => {
              chooseFile(event.target.files?.[0]);
            }}
          />
          {avatarUrl !== null || preview !== null ? (
            <Button
              type="button"
              variant="outline"
              disabled={uploading}
              onClick={() => void onRemove()}
            >
              <Trash2Icon aria-hidden="true" /> Remove
            </Button>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground">JPEG, PNG or WebP. Maximum 2 MB.</p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}
