import { notFound } from "next/navigation";
import { z } from "zod";

export const uuidParam = (value: string): string => {
  const parsed = z.uuid().safeParse(value);
  if (!parsed.success) {
    notFound();
  }
  return parsed.data;
};
