"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, UploadIcon } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Form } from "@/components/ui/form";
import { TrackFormFields } from "@/features/admin-music/components/track-form-fields";
import { adminMusicErrorMessage } from "@/features/admin-music/errors";
import { useUploadMusicTrack } from "@/features/admin-music/hooks/use-music-tracks";
import {
  emptyTrackFormValues,
  toUploadInput,
  type TrackFormValues,
  uploadFormSchema,
} from "@/features/admin-music/schemas/admin-music.schema";

interface UploadFormProps {
  onUploaded: () => void;
}

function UploadForm({ onUploaded }: UploadFormProps) {
  const upload = useUploadMusicTrack();
  const [failure, setFailure] = useState<unknown>(null);
  const form = useForm<TrackFormValues>({
    resolver: zodResolver(uploadFormSchema),
    defaultValues: emptyTrackFormValues,
  });
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      const track = await upload.mutateAsync(toUploadInput(values));
      toast.success(`Uploaded ${track.title}`);
      onUploaded();
    } catch (error) {
      setFailure(error);
    }
  });
  return (
    <Form {...form}>
      <form
        noValidate
        className="grid gap-4"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <TrackFormFields form={form} mode="upload" />
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminMusicErrorMessage(failure)}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={upload.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button type="submit" disabled={upload.isPending} aria-busy={upload.isPending}>
            {upload.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : (
              <UploadIcon aria-hidden="true" />
            )}
            {upload.isPending ? "Uploading and converting" : "Upload track"}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

export function UploadTrackDialog() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <UploadIcon aria-hidden="true" /> Upload track
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Upload a music track</DialogTitle>
          <DialogDescription>
            Only upload music you are licensed to use in generated videos. The license name and URL
            are shown to admins and credited beside videos.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <UploadForm
            onUploaded={() => {
              setOpen(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
