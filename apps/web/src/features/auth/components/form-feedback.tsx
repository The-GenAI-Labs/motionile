import type { Ref } from "react";
export function FormFeedback({
  message,
  errorRef,
}: {
  message: string;
  errorRef?: Ref<HTMLParagraphElement>;
}) {
  return (
    <p
      ref={errorRef}
      tabIndex={-1}
      role={message ? "alert" : undefined}
      aria-live="polite"
      className="text-sm text-destructive outline-none"
    >
      {message}
    </p>
  );
}
export function FieldError({ message }: { message?: string | undefined }) {
  return message ? (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  ) : null;
}
