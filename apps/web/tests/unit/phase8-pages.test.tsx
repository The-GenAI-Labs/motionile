import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as adminRenderDetail from "@/app/(super-admin)/admin/render/[renderId]/page";
import * as adminRender from "@/app/(super-admin)/admin/render/page";
import * as adminVoices from "@/app/(super-admin)/admin/voices/page";
import SettingsLayout from "@/app/(user)/settings/layout";
import * as newVoice from "@/app/(user)/settings/voices/new/page";
import * as voices from "@/app/(user)/settings/voices/page";
import { adminNavigation, settingsNavigation } from "@/config/navigation";

const { notFound, requirePermissions } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
  requirePermissions: vi.fn(() => Promise.resolve()),
}));

vi.mock("next/navigation", () => ({ notFound }));
vi.mock("@/lib/auth/require-permissions", () => ({ requirePermissions }));
vi.mock("@/features/admin-render/components/upload-render-form", () => ({
  UploadRenderForm: () => <form aria-label="Render a composition" />,
}));
vi.mock("@/features/admin-render/components/golden-list", () => ({
  GoldenList: () => <ul aria-label="Golden compositions" />,
}));
vi.mock("@/features/admin-render/components/render-monitor", () => ({
  RenderMonitor: ({ renderId }: { renderId: string }) => (
    <div role="region" aria-label={`Monitor ${renderId}`} />
  ),
}));
vi.mock("@/features/admin-voices/components/voices-table", () => ({
  VoicesTable: () => <div role="region" aria-label="Voices table" />,
}));
vi.mock("@/features/admin-voices/components/sync-voices-button", () => ({
  SyncVoicesButton: () => <button type="button">Sync from provider</button>,
}));
vi.mock("@/features/voices/components/voice-gallery", () => ({
  VoiceGallery: () => <div role="region" aria-label="Voice gallery" />,
}));
vi.mock("@/features/voices/components/lazy-clone-wizard", () => ({
  LazyCloneWizard: () => <div role="region" aria-label="Clone wizard" />,
}));

const RENDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e01";

describe("phase 8 pages", () => {
  it.each([
    ["/admin/render", adminRender.metadata],
    ["/admin/render", adminRenderDetail.metadata],
    ["/admin/voices", adminVoices.metadata],
    ["/settings/voices", voices.metadata],
    ["/settings/voices/new", newVoice.metadata],
  ])("%s is private and has a canonical url", (path, metadata) => {
    expect(metadata.robots).toEqual({ index: false, follow: false });
    expect(metadata.alternates?.canonical).toBe(`https://motionile.test${path}`);
    expect(metadata.description).toBeTruthy();
  });

  it("gives every page its own description", () => {
    const descriptions = [adminRender, adminRenderDetail, adminVoices, voices, newVoice].map(
      (page) => page.metadata.description,
    );

    expect(new Set(descriptions).size).toBe(descriptions.length);
  });

  it("guards the test bed with the render.testbed permission and lists both sections", async () => {
    render(await adminRender.default());

    expect(requirePermissions).toHaveBeenCalledWith(["render.testbed"]);
    expect(screen.getByRole("heading", { level: 1, name: "Render test bed" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upload a composition" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Golden compositions" })).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Render a composition" })).toBeInTheDocument();
  });

  it("opens the render monitor for a valid id and not found for an invalid one", async () => {
    render(await adminRenderDetail.default({ params: Promise.resolve({ renderId: RENDER_ID }) }));

    expect(screen.getByRole("region", { name: `Monitor ${RENDER_ID}` })).toBeInTheDocument();
    await expect(
      adminRenderDetail.default({ params: Promise.resolve({ renderId: "nope" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("guards the voice catalog with the voices.manage permission", async () => {
    render(await adminVoices.default());

    expect(requirePermissions).toHaveBeenCalledWith(["voices.manage"]);
    expect(screen.getByRole("heading", { level: 1, name: "Voice catalog" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync from provider" })).toBeInTheDocument();
  });

  it("links the cloning wizard from the voices page", () => {
    render(voices.default());

    expect(screen.getByRole("heading", { level: 1, name: "Voices" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Clone your voice" })).toHaveAttribute(
      "href",
      "/settings/voices/new",
    );
    expect(screen.getByRole("region", { name: "Voice gallery" })).toBeInTheDocument();
  });

  it("renders the wizard page", () => {
    render(newVoice.default());

    expect(screen.getByRole("heading", { level: 1, name: "Clone your voice" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Clone wizard" })).toBeInTheDocument();
  });
});

describe("phase 8 navigation", () => {
  it("adds the test bed and voices to the admin navigation behind their permissions", () => {
    const items = adminNavigation.items as readonly {
      title: string;
      href: string;
      permission: string;
    }[];

    expect(items.find((item) => item.href === "/admin/render")).toMatchObject({
      title: "Render test bed",
      permission: "render.testbed",
    });
    expect(items.find((item) => item.href === "/admin/voices")).toMatchObject({
      title: "Voices",
      permission: "voices.manage",
    });
  });

  it("adds Voices to the account settings tabs", () => {
    expect(settingsNavigation.map((item) => item.href)).toEqual([
      "/settings/profile",
      "/settings/voices",
      "/settings/security",
    ]);
    render(
      <SettingsLayout>
        <p>Body</p>
      </SettingsLayout>,
    );

    const nav = screen.getByRole("navigation", { name: "Account settings" });

    expect(within(nav).getByRole("link", { name: "Voices" })).toHaveAttribute(
      "href",
      "/settings/voices",
    );
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Profile", "Voices", "Security"]);
  });
});
