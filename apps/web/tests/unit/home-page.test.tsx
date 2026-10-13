import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage, { metadata } from "@/app/(public)/page";

describe("home page", () => {
  it("shows the product name as the main heading", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { level: 1, name: "Motionile" })).toBeInTheDocument();
  });

  it("shows the value proposition", () => {
    render(<HomePage />);

    expect(
      screen.getByText("Turn any topic into a narrated, animated explainer video."),
    ).toBeInTheDocument();
  });

  it("renders the primary call to action as an accessible link", () => {
    render(<HomePage />);

    const action = screen.getByRole("link", { name: "See how it works" });
    expect(action).toHaveAttribute("href", "#how-it-works");
    expect(action).toHaveAttribute("data-slot", "button");
  });

  it("lists the three steps in order", () => {
    render(<HomePage />);

    const steps = screen
      .getAllByRole("listitem")
      .map((item) => item.querySelector("h3")?.textContent);
    expect(steps).toEqual(["Plan", "Narrate", "Animate"]);
  });

  it("uses the absolute default title", () => {
    expect(metadata.title).toEqual({ absolute: "Motionile — AI Animated Explainer Videos" });
  });
});
