interface MusicCreditProps {
  title: string;
  licenseName: string;
  licenseUrl: string | null;
  attributionText: string | null;
}

export function MusicCredit({ title, licenseName, licenseUrl, attributionText }: MusicCreditProps) {
  return (
    <p className="text-xs text-muted-foreground">
      Music: <cite className="text-subtle-foreground not-italic">{title}</cite>
      {attributionText ? `. ${attributionText}` : ""}. License:{" "}
      {licenseUrl ? (
        <a
          href={licenseUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-sm underline underline-offset-4 hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          {licenseName}
        </a>
      ) : (
        licenseName
      )}
      .
    </p>
  );
}
