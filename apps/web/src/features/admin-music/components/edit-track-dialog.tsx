"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, PencilIcon } from "lucide-react";
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
import { adminMusicErrorMessage, adminMusicGuidance } from "@/features/admin-music/errors";
import { useUpdateMusicTrack } from "@/features/admin-music/hooks/use-music-tracks";
import {
  hasUpdateChanges,
  toUpdateInput,
  trackFormSchema,
  type TrackFormValues,
  trackFormValues,
} from "@/features/admin-music/schemas/admin-music.schema";
import type { MusicTrack } from "@/features/admin-music/types/admin-music.types";

interface EditFormProps {
  track: MusicTrack;
  onSaved: () => void;
}

function EditForm({ track, onSaved }: EditFormProps) {
  const update = useUpdateMusicTrack(track.id);
  const [failure, setFailure] = useState<unknown>(null);
  const [unchanged, setUnchanged] = useState(false);
  const form = useForm<TrackFormValues>({
    resolver: zodResolver(trackFormSchema),
    defaultValues: trackFormValues(track),
  });
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    const changes = toUpdateInput(values, track);
    setUnchanged(!hasUpdateChanges(changes));
    if (!hasUpdateChanges(changes)) {
      return;
    }
    try {
      await update.mutateAsync(changes);
      toast.success(`Saved ${values.title}`);
      onSaved();
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
        <TrackFormFields form={form} mode="edit" />
        {unchanged ? (
          <p role="alert" className="text-sm text-destructive">
            {adminMusicGuidance["music_update_empty"]}
          </p>
        ) : null}
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminMusicErrorMessage(failure)}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={update.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button type="submit" disabled={update.isPending} aria-busy={update.isPending}>
            {update.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Save changes
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

export function EditTrackDialog({ track }: { track: MusicTrack }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" aria-label={`Edit ${track.title}`}>
          <PencilIcon aria-hidden="true" /> Edit
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit track</DialogTitle>
          <DialogDescription>
            Change the metadata and license of {track.title}. The audio file cannot be replaced;
            upload a new track instead.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <EditForm
            track={track}
            onSaved={() => {
              setOpen(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
