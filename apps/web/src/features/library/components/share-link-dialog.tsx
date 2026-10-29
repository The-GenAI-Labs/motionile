"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CopyIcon, Loader2Icon, Share2Icon } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
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
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { libraryErrorMessage } from "@/features/library/errors";
import { useCreateShareLink, useRevokeShareLinks } from "@/features/library/hooks/use-library";
import {
  ASPECT_ORDER,
  aspectDescriptions,
  aspectLabels,
  playableRenditions,
  shareFormSchema,
  type ShareFormValues,
} from "@/features/library/schemas/library.schema";
import type { LibraryItem, ShareLink } from "@/features/library/types/library.types";
import { absoluteUrl } from "@/lib/seo/metadata";

const shareableAspects = (item: LibraryItem) => {
  const ready = playableRenditions(item.renditions).map((rendition) => rendition.aspect);
  return ASPECT_ORDER.filter((aspect) => ready.includes(aspect));
};

const copyToClipboard = async (url: string): Promise<void> => {
  try {
    await navigator.clipboard.writeText(url);
    toast.success("Link copied");
  } catch {
    toast.error("The link could not be copied. Select it and copy it by hand.");
  }
};

function LinkField({ url }: { url: string }) {
  return (
    <div className="space-y-2">
      <Label htmlFor="share-link-url">Public link</Label>
      <div className="flex gap-2">
        <Input
          id="share-link-url"
          readOnly
          value={url}
          className="font-mono text-xs"
          onFocus={(event) => {
            event.currentTarget.select();
          }}
        />
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void copyToClipboard(url);
          }}
        >
          <CopyIcon aria-hidden="true" /> Copy link
        </Button>
      </div>
    </div>
  );
}

function RevokeLinks({ item }: { item: LibraryItem }) {
  const revoke = useRevokeShareLinks(item.jobId);
  const [open, setOpen] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setFailure(null);
        }
      }}
      trigger={
        <Button type="button" variant="outline">
          Turn off sharing
        </Button>
      }
      title="Turn off sharing?"
      description="Every public link to this video stops working. You can create a new link later."
      confirmLabel="Turn off sharing"
      destructive
      error={failure === null ? null : libraryErrorMessage(failure)}
      onConfirm={async () => {
        setFailure(null);
        try {
          await revoke.mutateAsync();
        } catch (error) {
          setFailure(error);
          throw error;
        }
        toast.success("Sharing is turned off");
      }}
    />
  );
}

interface ShareFormProps {
  item: LibraryItem;
  onCreated: (link: ShareLink) => void;
}

function ShareForm({ item, onCreated }: ShareFormProps) {
  const aspects = shareableAspects(item);
  const create = useCreateShareLink(item.jobId);
  const [failure, setFailure] = useState<unknown>(null);
  const form = useForm<ShareFormValues>({
    resolver: zodResolver(shareFormSchema),
    defaultValues: { aspect: aspects[0] ?? "16:9", allowIndexing: false },
  });
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      onCreated(await create.mutateAsync(values));
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
        <FormField
          control={form.control}
          name="aspect"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Version to share</FormLabel>
              <FormControl>
                <NativeSelect {...field}>
                  {aspects.map((aspect) => (
                    <option key={aspect} value={aspect}>
                      {aspectLabels[aspect]} {aspectDescriptions[aspect].toLowerCase()}
                    </option>
                  ))}
                </NativeSelect>
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="allowIndexing"
          render={({ field }) => (
            <FormItem>
              <div className="flex items-center gap-3">
                <FormControl>
                  <Switch checked={field.value} onCheckedChange={field.onChange} />
                </FormControl>
                <FormLabel>Let search engines index the page</FormLabel>
              </div>
              <FormDescription>
                Off by default. Anyone with the link can watch either way.
              </FormDescription>
            </FormItem>
          )}
        />
        {item.shareSlug === null ? null : (
          <p className="text-sm text-muted-foreground">
            This video is already shared. Creating a new link turns off the previous one.
          </p>
        )}
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {libraryErrorMessage(failure)}
          </p>
        )}
        <DialogFooter>
          {item.shareSlug === null ? null : <RevokeLinks item={item} />}
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={create.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="submit"
            disabled={create.isPending || aspects.length === 0}
            aria-busy={create.isPending}
          >
            {create.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Create link
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

function CreatedLink({ link }: { link: ShareLink }) {
  return (
    <div className="space-y-4">
      <LinkField url={link.url} />
      <p className="text-sm text-muted-foreground">
        Sharing the {aspectLabels[link.aspect]} version.{" "}
        {link.allowIndexing
          ? "Search engines may index the page."
          : "Search engines are asked not to index the page."}
      </p>
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button">Done</Button>
        </DialogClose>
      </DialogFooter>
    </div>
  );
}

export function ShareLinkDialog({ item }: { item: LibraryItem }) {
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<ShareLink | null>(null);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setCreated(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" aria-label={`Share ${item.title}`}>
          <Share2Icon aria-hidden="true" /> Share
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Share this video</DialogTitle>
          <DialogDescription>
            Create a public link to {item.title}. It opens on Motionile without signing in.
          </DialogDescription>
        </DialogHeader>
        {open && created !== null ? <CreatedLink link={created} /> : null}
        {open && created === null ? (
          <>
            {item.shareSlug === null ? null : (
              <LinkField url={absoluteUrl(`/v/${item.shareSlug}`)} />
            )}
            <ShareForm item={item} onCreated={setCreated} />
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
