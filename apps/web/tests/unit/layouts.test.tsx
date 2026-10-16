import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PublicLayout from "@/app/(public)/layout";
import { AdminShell } from "@/components/layouts/admin-shell";
import { PublicFooter } from "@/components/layouts/public-footer";
import { PublicHeader } from "@/components/layouts/public-header";
import { UserShell } from "@/components/layouts/user-shell";

vi.mock("@/features/auth/hooks/use-current-user", () => ({
  useCurrentUser: () => ({ data: { name: "Test user" } }),
}));
vi.mock("@/features/auth/hooks/use-auth-mutations", () => ({
  useLogout: () => ({ mutate: vi.fn(), isPending: false }),
}));

const pathname = vi.hoisted(() => ({ current: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
}));

beforeEach(() => {
  pathname.current = "/";
});

describe("public layout", () => {
  it("wraps pages with a skip link, header, main landmark and footer", () => {
    render(
      <PublicLayout>
        <p>content</p>
      </PublicLayout>,
    );

    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("banner")).toHaveTextContent("Motionile");
    expect(screen.getByRole("main")).toHaveTextContent("content");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Motionile");
  });

  it("links the primary pages from the header", () => {
    render(<PublicHeader />);

    const primary = screen.getByRole("navigation", { name: "Primary" });
    expect(within(primary).getByRole("link", { name: "Pricing" })).toHaveAttribute(
      "href",
      "/pricing",
    );
    expect(within(primary).getByRole("link", { name: "About" })).toHaveAttribute("href", "/about");
    expect(within(primary).getByRole("link", { name: "Contact" })).toHaveAttribute(
      "href",
      "/contact",
    );
    expect(screen.getAllByRole("link", { name: "Motionile" })[0]).toHaveAttribute("href", "/");
  });

  it("opens the mobile navigation in a sheet and closes it after navigating", async () => {
    const user = userEvent.setup();
    render(<PublicHeader />);

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    const dialog = screen.getByRole("dialog");
    const mobileNav = within(dialog).getByRole("navigation", { name: "Mobile" });
    expect(
      within(mobileNav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Pricing", "About", "Contact"]);

    await user.click(within(mobileNav).getByRole("link", { name: "Pricing" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("links legal pages from the footer", () => {
    render(<PublicFooter />);

    const legal = screen.getByRole("navigation", { name: "Legal" });
    expect(within(legal).getByRole("link", { name: "Terms of Service" })).toHaveAttribute(
      "href",
      "/legal/terms",
    );
    expect(within(legal).getByRole("link", { name: "Privacy Policy" })).toHaveAttribute(
      "href",
      "/legal/privacy",
    );
    expect(
      within(legal).getByRole("link", { name: "Refund and Cancellation Policy" }),
    ).toHaveAttribute("href", "/legal/refund-policy");
    expect(within(legal).getByRole("link", { name: "Data Deletion" })).toHaveAttribute(
      "href",
      "/legal/data-deletion",
    );
    expect(screen.getByRole("navigation", { name: "Product" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Company" })).toBeInTheDocument();
  });
});

describe("user shell", () => {
  it("renders the sidebar navigation and marks the current page", () => {
    pathname.current = "/library/abc";
    render(
      <UserShell>
        <h1>Library</h1>
      </UserShell>,
    );

    const sidebar = screen.getByRole("complementary", { name: "Workspace sidebar" });
    const nav = within(sidebar).getByRole("navigation", { name: "Workspace" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Dashboard", "Create", "Library", "Publications", "Skills", "Billing", "Settings"]);
    expect(within(nav).getByRole("link", { name: "Library" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Dashboard" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("main")).toContainElement(
      screen.getByRole("heading", { name: "Library" }),
    );
  });

  it("opens the mobile sidebar and closes it after navigating", async () => {
    const user = userEvent.setup();
    render(
      <UserShell>
        <p>content</p>
      </UserShell>,
    );

    await user.click(screen.getByRole("button", { name: "Open workspace navigation" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("link", { name: "Create" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers account actions from the account menu", async () => {
    const user = userEvent.setup();
    render(
      <UserShell>
        <p>content</p>
      </UserShell>,
    );

    await user.click(screen.getByRole("button", { name: "Account menu" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Admin console" })).toHaveAttribute(
      "href",
      "/admin",
    );
    expect(within(menu).getByRole("menuitem", { name: "Billing" })).toHaveAttribute(
      "href",
      "/billing",
    );
    expect(within(menu).getByRole("menuitem", { name: "Settings" })).toHaveAttribute(
      "href",
      "/settings/security",
    );
    expect(within(menu).getByRole("menuitem", { name: "Back to site" })).toHaveAttribute(
      "href",
      "/",
    );
  });
});

describe("admin shell", () => {
  it("renders the admin navigation with an exact match for the overview", () => {
    pathname.current = "/admin/users";
    render(
      <AdminShell>
        <p>content</p>
      </AdminShell>,
    );

    const nav = screen.getByRole("navigation", { name: "Admin" });
    expect(within(nav).getByRole("link", { name: "Users" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("link", { name: "Audit logs" })).toHaveAttribute(
      "href",
      "/admin/audit-logs",
    );
  });

  it("links back to the workspace from the account menu", async () => {
    const user = userEvent.setup();
    render(
      <AdminShell>
        <p>content</p>
      </AdminShell>,
    );

    await user.click(screen.getByRole("button", { name: "Account menu" }));

    expect(screen.getByRole("menuitem", { name: "Workspace" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });
});
