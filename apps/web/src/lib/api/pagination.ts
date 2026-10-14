import { z } from "zod";

export const cursorPageSchema = <ItemSchema extends z.ZodType>(itemSchema: ItemSchema) =>
  z.object({
    items: z.array(itemSchema),
    nextCursor: z.string().nullish(),
  });

export interface CursorPage<Item> {
  items: Item[];
  nextCursor?: string | null | undefined;
}

export const getNextPageParam = <Item>(lastPage: CursorPage<Item>): string | undefined =>
  lastPage.nextCursor ?? undefined;

export const flattenCursorPages = <Item>(pages: readonly CursorPage<Item>[] | undefined): Item[] =>
  pages?.flatMap((page) => page.items) ?? [];
