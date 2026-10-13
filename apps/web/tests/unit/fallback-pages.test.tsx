import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PublicLayout from "@/app/(public)/layout";
import ErrorPage from "@/app/error";
import NotFound from "@/app/not-found";

describe("fallback pages", () => {
  it("links back home from the not found page", () => {
    render(<NotFound />);

    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to home" })).toHaveAttribute("href", "/");
  });

  it("retries from the error page", () => {
    const reset = vi.fn();
    render(<ErrorPage error={new Error("boom")} reset={reset} />);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(reset).toHaveBeenCalledOnce();
  });

  it("wraps public pages with a header, main landmark and footer", () => {
    render(
      <PublicLayout>
        <p>content</p>
      </PublicLayout>,
    );

    expect(screen.getByRole("banner")).toHaveTextContent("Motionile");
    expect(screen.getByRole("main")).toHaveTextContent("content");
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Motionile");
  });
});
