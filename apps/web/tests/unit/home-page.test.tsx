import { render, screen, within } from "@testing-library/react";
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

  it("renders the primary calls to action as accessible links", () => {
    render(<HomePage />);

    const action = screen.getByRole("link", { name: "See how it works" });
    expect(action).toHaveAttribute("href", "#how-it-works");
    expect(action).toHaveAttribute("data-slot", "button");
    expect(screen.getByRole("link", { name: "See pricing" })).toHaveAttribute("href", "/pricing");
  });

  it("lists the four steps in order", () => {
    render(<HomePage />);

    const steps = within(screen.getByRole("list", { name: "Steps" }))
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(steps).toEqual(["Topic", "Storyboard", "Narration", "Video"]);
  });

  it("showcases categories with sample topics", () => {
    render(<HomePage />);

    const categories = screen.getByRole("list", { name: "Categories" });
    expect(within(categories).getByRole("heading", { name: "Education" })).toBeInTheDocument();
    expect(within(categories).getByRole("heading", { name: "System Design" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Cybersecurity sample topics" })).toBeInTheDocument();
  });

  it("emits Organization and SoftwareApplication JSON-LD", () => {
    const { container } = render(<HomePage />);
    const script = container.querySelector('script[type="application/ld+json"]');
    const data = JSON.parse(script?.textContent ?? "[]") as { "@type": string }[];

    expect(data.map((item) => item["@type"])).toEqual(["Organization", "SoftwareApplication"]);
  });

  it("uses the absolute default title and the home canonical url", () => {
    expect(metadata.title).toEqual({ absolute: "Motionile — AI Animated Explainer Videos" });
    expect(metadata.alternates?.canonical).toBe("https://motionile.test/");
  });
});
