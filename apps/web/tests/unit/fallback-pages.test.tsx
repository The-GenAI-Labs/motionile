import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ErrorPage from "@/app/error";
import Forbidden, { metadata as forbiddenMetadata } from "@/app/forbidden";
import GlobalError from "@/app/global-error";
import NotFound, { metadata as notFoundMetadata } from "@/app/not-found";

describe("fallback pages", () => {
  it("links back home from the not found page and is not indexed", () => {
    render(<NotFound />);

    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Contact support" })).toHaveAttribute(
      "href",
      "/contact",
    );
    expect(notFoundMetadata.robots).toEqual({ index: false, follow: false });
  });

  it("explains a forbidden page", () => {
    render(<Forbidden />);

    expect(screen.getByRole("heading", { level: 1, name: "Access denied" })).toBeInTheDocument();
    expect(screen.getByText("403")).toBeInTheDocument();
    expect(forbiddenMetadata.robots).toEqual({ index: false, follow: false });
  });

  it("retries from the error page and shows the error reference", () => {
    const reset = vi.fn();
    render(
      <ErrorPage error={Object.assign(new Error("boom"), { digest: "abc123" })} reset={reset} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(reset).toHaveBeenCalledOnce();
    expect(screen.getByText("Error reference abc123")).toBeInTheDocument();
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
  });

  it("retries from the global error page", () => {
    const reset = vi.fn();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<GlobalError error={new Error("boom")} reset={reset} />);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(reset).toHaveBeenCalledOnce();
    expect(screen.getByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
    consoleError.mockRestore();
  });
});
