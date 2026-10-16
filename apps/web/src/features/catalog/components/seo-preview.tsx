import { cn } from "@/lib/utils/cn";

export const SEO_TITLE_TARGET = 60;
export const SEO_DESCRIPTION_TARGET = 160;

export const seoLengthState = (value: string, maximum: number): "empty" | "good" | "long" => {
  if (value.trim().length === 0) {
    return "empty";
  }
  return value.length <= maximum ? "good" : "long";
};

interface SeoPreviewProps {
  title: string;
  description: string;
  path: string;
}

export function SeoPreview({ title, description, path }: SeoPreviewProps) {
  const titleState = seoLengthState(title, SEO_TITLE_TARGET);
  const descriptionState = seoLengthState(description, SEO_DESCRIPTION_TARGET);
  return (
    <section
      aria-labelledby="seo-preview-title"
      className="space-y-3 rounded-xl border bg-surface p-5"
    >
      <div className="flex items-center justify-between gap-4">
        <h3 id="seo-preview-title" className="font-semibold">
          Search result preview
        </h3>
        <span className="font-mono text-xs text-muted-foreground">{path}</span>
      </div>
      <div className="space-y-1 rounded-lg bg-background p-4">
        <p className="text-lg text-foreground">{title || "SEO title"}</p>
        <p className="text-sm text-subtle-foreground">{description || "SEO description"}</p>
      </div>
      <div className="flex flex-wrap gap-4 text-xs">
        <p className={cn("text-muted-foreground", titleState === "long" && "text-destructive")}>
          Title {title.length}/{SEO_TITLE_TARGET}
          {titleState === "long" ? " — shorten this title" : ""}
        </p>
        <p
          className={cn("text-muted-foreground", descriptionState === "long" && "text-destructive")}
        >
          Description {description.length}/{SEO_DESCRIPTION_TARGET}
          {descriptionState === "long" ? " — shorten this description" : ""}
        </p>
      </div>
    </section>
  );
}
