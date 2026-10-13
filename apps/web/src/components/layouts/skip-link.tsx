export const MAIN_CONTENT_ID = "main";

export function SkipLink() {
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      className="sr-only rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50 focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
    >
      Skip to content
    </a>
  );
}
