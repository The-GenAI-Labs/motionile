"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2Icon, PlayIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

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
import { RenderChoicesFields } from "@/features/admin-render/components/render-choices-fields";
import { adminRenderErrorMessage } from "@/features/admin-render/errors";
import { useCreateGoldenRender } from "@/features/admin-render/hooks/use-testbed";
import {
  emptyGoldenFormValues,
  goldenFormSchema,
  type GoldenFormValues,
} from "@/features/admin-render/schemas/admin-render.schema";
import type { GoldenComposition } from "@/features/admin-render/types/admin-render.types";

interface GoldenFormProps {
  golden: GoldenComposition;
}

function GoldenForm({ golden }: GoldenFormProps) {
  const router = useRouter();
  const create = useCreateGoldenRender(golden.name);
  const [failure, setFailure] = useState<unknown>(null);
  const form = useForm<GoldenFormValues>({
    resolver: zodResolver(goldenFormSchema),
    defaultValues: emptyGoldenFormValues(),
  });

  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      const render = await create.mutateAsync(values);
      router.push(`/admin/render/${render.id}`);
    } catch (error) {
      setFailure(error);
    }
  });

  return (
    <Form {...form}>
      <form
        noValidate
        className="grid gap-5"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <RenderChoicesFields showVoice idPrefix={`golden-${golden.name}`} />
        {failure === null ? null : (
          <p role="alert" className="text-sm text-destructive">
            {adminRenderErrorMessage(failure)}
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={create.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button type="submit" disabled={create.isPending} aria-busy={create.isPending}>
            {create.isPending ? (
              <Loader2Icon aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : null}
            Start render
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}

export function GoldenRenderDialog({ golden }: GoldenFormProps) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" aria-label={`Render ${golden.title}`}>
          <PlayIcon aria-hidden="true" /> Render
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{`Render ${golden.title}`}</DialogTitle>
          <DialogDescription>
            Uses the narration text that ships with this golden composition. Choose the voice and
            output options.
          </DialogDescription>
        </DialogHeader>
        {open ? <GoldenForm golden={golden} /> : null}
      </DialogContent>
    </Dialog>
  );
}
