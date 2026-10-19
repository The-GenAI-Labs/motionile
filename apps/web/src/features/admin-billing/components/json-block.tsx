interface JsonBlockProps {
  label: string;
  value: unknown;
}

export function JsonBlock({ label, value }: JsonBlockProps) {
  return (
    <pre
      tabIndex={0}
      aria-label={label}
      className="max-h-96 overflow-auto rounded-lg border bg-background p-3 font-mono text-xs focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
