"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, PencilIcon } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
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
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { TagInput } from "@/features/admin-voices/components/tag-input";
import { adminVoiceErrorMessage } from "@/features/admin-voices/errors";
import { useUpdateAdminVoice } from "@/features/admin-voices/hooks/use-admin-voices";
import {
  editValuesFor,
  hasVoiceChanges,
  toVoiceUpdate,
  voiceEditSchema,
  type VoiceEditValues,
} from "@/features/admin-voices/schemas/admin-voices.schema";
import type { AdminVoice } from "@/features/admin-voices/types/admin-voices.types";

interface EditFormProps {
  voice: AdminVoice;
  onSaved: () => void;
}

function EditForm({ voice, onSaved }: EditFormProps) {
  const update = useUpdateAdminVoice(voice.id);
  const [failure, setFailure] = useState<unknown>(null);
  const [unchanged, setUnchanged] = useState(false);
  const form = useForm<VoiceEditValues>({
    resolver: zodResolver(voiceEditSchema),
    defaultValues: editValuesFor(voice),
  });
  const exposedValue = useWatch({ control: form.control, name: "exposed" });
  const exposing = exposedValue && voice.status !== "ready";

  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    const changes = toVoiceUpdate(values, voice);
    setUnchanged(!hasVoiceChanges(changes));
    if (!hasVoiceChanges(changes)) {
      return;
    }
    try {
      await update.mutateAsync(changes);
      toast.success(`Saved ${values.name}`);
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
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input autoComplete="off" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="language"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Language</FormLabel>
                <FormControl>
                  <Input autoComplete="off" className="font-mono" {...field} />
                </FormControl>
                <FormDescription>A language code such as en or hi.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        <FormField
          control={form.control}
          name="tags"
          render={({ field }) => (
            <FormItem>
              <TagInput label="Tags" value={field.value} onChange={field.onChange} />
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="exposed"
          render={({ field }) => (
            <FormItem>
              <div className="flex items-start gap-3">
                <FormControl>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </FormControl>
                <div className="grid gap-1">
                  <FormLabel>Expose to users</FormLabel>
                  <FormDescription>
                    Exposed voices appear in the voice list of every user and in the render test
                    bed. Exposing a voice generates its preview clip, which can take a few seconds.
                  </FormDescription>
                </div>
              </div>
            </FormItem>
          )}
        />
        {exposing ? (
          <p role="status" className="text-sm text-muted-foreground">
            Saving will generate a preview for this voice before it is exposed.
          </p>
        ) : null}
        {unchanged ? (
          <p role="alert" className="text-sm text-destructive">
            Change at least one field before saving.
          </p>
        ) : null}
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminVoiceErrorMessage(failure)}
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

export function EditVoiceDialog({ voice }: { voice: AdminVoice }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" aria-label={`Edit ${voice.name}`}>
          <PencilIcon aria-hidden="true" /> Edit
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit voice</DialogTitle>
          <DialogDescription>
            Curate how {voice.name} appears to users. The provider voice itself cannot be changed.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <EditForm
            voice={voice}
            onSaved={() => {
              setOpen(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
