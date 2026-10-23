"use client";

import type { UseFormReturn } from "react-hook-form";

import { Checkbox } from "@/components/ui/checkbox";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  MAX_BPM,
  MIN_BPM,
  MUSIC_MAX_BYTES,
  type TrackFormValues,
} from "@/features/admin-music/schemas/admin-music.schema";

export const AUDIO_ACCEPT = "audio/*,.mp3,.m4a,.aac,.wav,.flac,.ogg,.mka";

const MAX_MEGABYTES = MUSIC_MAX_BYTES / (1024 * 1024);

interface TrackFormFieldsProps {
  form: UseFormReturn<TrackFormValues>;
  mode: "upload" | "edit";
}

export function TrackFormFields({ form, mode }: TrackFormFieldsProps) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {mode === "upload" ? (
        <FormField
          control={form.control}
          name="file"
          render={({ field }) => (
            <FormItem className="sm:col-span-2">
              <FormLabel>Audio file</FormLabel>
              <FormControl>
                <Input
                  type="file"
                  accept={AUDIO_ACCEPT}
                  name={field.name}
                  ref={field.ref}
                  onBlur={field.onBlur}
                  onChange={(event) => {
                    field.onChange(event.target.files?.[0]);
                  }}
                />
              </FormControl>
              <FormDescription>
                {`Audio only, from 5 seconds to 15 minutes, up to ${String(MAX_MEGABYTES)} MB. It is converted to M4A.`}
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      ) : null}
      <FormField
        control={form.control}
        name="title"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Title</FormLabel>
            <FormControl>
              <Input autoComplete="off" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="mood"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Mood</FormLabel>
            <FormControl>
              <Input autoComplete="off" className="font-mono" {...field} />
            </FormControl>
            <FormDescription>Lowercase, for example calm, upbeat or cinematic.</FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="bpm"
        render={({ field }) => (
          <FormItem>
            <FormLabel>BPM (optional)</FormLabel>
            <FormControl>
              <Input inputMode="numeric" autoComplete="off" className="font-mono" {...field} />
            </FormControl>
            <FormDescription>{`From ${String(MIN_BPM)} to ${String(MAX_BPM)}.`}</FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="licenseName"
        render={({ field }) => (
          <FormItem>
            <FormLabel>License name</FormLabel>
            <FormControl>
              <Input autoComplete="off" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="licenseUrl"
        render={({ field }) => (
          <FormItem className="sm:col-span-2">
            <FormLabel>License URL</FormLabel>
            <FormControl>
              <Input type="url" autoComplete="off" inputMode="url" {...field} />
            </FormControl>
            <FormDescription>An https link to the license terms.</FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="attributionText"
        render={({ field }) => (
          <FormItem className="sm:col-span-2">
            <FormLabel>Attribution text (optional)</FormLabel>
            <FormControl>
              <Textarea rows={2} {...field} />
            </FormControl>
            <FormDescription>Shown beside videos that use this track.</FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
      {mode === "upload" ? (
        <FormField
          control={form.control}
          name="activate"
          render={({ field }) => (
            <FormItem className="sm:col-span-2">
              <div className="flex items-start gap-3">
                <FormControl>
                  <Checkbox
                    checked={field.value}
                    onCheckedChange={(checked) => {
                      field.onChange(checked === true);
                    }}
                  />
                </FormControl>
                <div className="grid gap-1">
                  <FormLabel>Activate on upload</FormLabel>
                  <FormDescription>
                    Leave it off to review the track first. Inactive tracks cannot be used in
                    renders.
                  </FormDescription>
                </div>
              </div>
            </FormItem>
          )}
        />
      ) : null}
    </div>
  );
}
