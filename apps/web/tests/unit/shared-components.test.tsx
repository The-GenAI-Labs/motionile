import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Inbox } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { CursorPagination } from "@/components/shared/cursor-pagination";
import { EmptyState } from "@/components/shared/empty-state";
import { LoadingSpinner } from "@/components/shared/loading-spinner";
import { PageHeader } from "@/components/shared/page-header";
import { hasPermissions, PermissionGate } from "@/components/shared/permission-gate";
import { Button } from "@/components/ui/button";

describe("PageHeader", () => {
  it("renders a level one heading with description and actions", () => {
    render(
      <PageHeader
        eyebrow="Library"
        title="Your videos"
        description="Everything you have generated."
        actions={<Button>New video</Button>}
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Your videos" })).toBeInTheDocument();
    expect(screen.getByText("Everything you have generated.")).toBeInTheDocument();
    expect(screen.getByText("Library")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New video" })).toBeInTheDocument();
  });

  it("renders only the title when nothing else is given", () => {
    render(<PageHeader title="Plain" />);

    expect(screen.getByRole("heading", { name: "Plain" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("renders a labelled region with its heading, description and action", () => {
    render(
      <EmptyState
        icon={Inbox}
        title="No videos yet"
        description="Create your first explainer."
        action={<Button>Create video</Button>}
      />,
    );

    const region = screen.getByRole("region", { name: "No videos yet" });
    expect(within(region).getByRole("heading", { level: 2, name: "No videos yet" })).toBeVisible();
    expect(within(region).getByText("Create your first explainer.")).toBeInTheDocument();
    expect(within(region).getByRole("button", { name: "Create video" })).toBeInTheDocument();
  });

  it("supports a level three heading", () => {
    render(<EmptyState title="Nothing here" headingLevel={3} />);

    expect(screen.getByRole("heading", { level: 3, name: "Nothing here" })).toBeInTheDocument();
  });
});

describe("LoadingSpinner", () => {
  it("announces a status with a default label", () => {
    render(<LoadingSpinner />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });

  it("can show a custom visible label", () => {
    render(<LoadingSpinner label="Rendering video" showLabel />);

    expect(screen.getByRole("status")).toHaveTextContent("Rendering video");
    expect(screen.getByText("Rendering video")).toBeVisible();
  });
});

describe("PermissionGate", () => {
  it("checks all or any required permissions", () => {
    expect(hasPermissions([], [])).toBe(true);
    expect(hasPermissions(["a", "b"], ["a", "b", "c"])).toBe(true);
    expect(hasPermissions(["a", "b"], ["a"])).toBe(false);
    expect(hasPermissions(["a", "b"], ["b"], "any")).toBe(true);
    expect(hasPermissions(["a", "b"], ["c"], "any")).toBe(false);
  });

  it("renders children when every permission is granted", () => {
    render(
      <PermissionGate required={["users.read"]} granted={["users.read", "users.write"]}>
        <Button>Edit users</Button>
      </PermissionGate>,
    );

    expect(screen.getByRole("button", { name: "Edit users" })).toBeInTheDocument();
  });

  it("renders the fallback when a permission is missing", () => {
    render(
      <PermissionGate
        required={["users.write"]}
        granted={["users.read"]}
        fallback={<p>You cannot edit users.</p>}
      >
        <Button>Edit users</Button>
      </PermissionGate>,
    );

    expect(screen.queryByRole("button", { name: "Edit users" })).not.toBeInTheDocument();
    expect(screen.getByText("You cannot edit users.")).toBeInTheDocument();
  });

  it("renders nothing by default when denied", () => {
    const { container } = render(
      <PermissionGate required={["a"]} granted={[]}>
        <p>secret</p>
      </PermissionGate>,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

describe("CursorPagination", () => {
  it("loads the next page when the button is pressed", async () => {
    const user = userEvent.setup();
    const fetchNextPage = vi.fn();
    render(
      <CursorPagination hasNextPage isFetchingNextPage={false} fetchNextPage={fetchNextPage} />,
    );

    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(fetchNextPage).toHaveBeenCalledOnce();
  });

  it("is keyboard operable", async () => {
    const user = userEvent.setup();
    const fetchNextPage = vi.fn();
    render(
      <CursorPagination hasNextPage isFetchingNextPage={false} fetchNextPage={fetchNextPage} />,
    );

    await user.tab();
    expect(screen.getByRole("button", { name: "Load more" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(fetchNextPage).toHaveBeenCalledOnce();
  });

  it("disables the button while the next page is loading", () => {
    render(<CursorPagination hasNextPage isFetchingNextPage fetchNextPage={vi.fn()} />);

    const button = screen.getByRole("button", { name: "Load more" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("shows the end of the list when there are no more pages", () => {
    render(
      <CursorPagination
        hasNextPage={false}
        isFetchingNextPage={false}
        fetchNextPage={vi.fn()}
        endLabel="No more videos."
      />,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("No more videos.")).toBeInTheDocument();
  });
});

describe("ConfirmDialog", () => {
  it("opens from its trigger and confirms", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Delete video?"
        description="This cannot be undone."
        confirmLabel="Delete"
        destructive
        onConfirm={onConfirm}
        trigger={<Button>Delete video</Button>}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Delete video" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete video?" });
    expect(dialog).toHaveAccessibleDescription("This cannot be undone.");

    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(onConfirm).toHaveBeenCalledOnce();
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
  });

  it("closes without confirming on cancel or Escape", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Leave?"
        description="Unsaved changes will be lost."
        onConfirm={onConfirm}
        trigger={<Button>Leave</Button>}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Leave" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Leave" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("stays open and busy while an async confirmation runs, then closes", async () => {
    const user = userEvent.setup();
    let resolve: () => void = () => undefined;
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Cancel subscription?"
        description="It ends at the end of the period."
        confirmLabel="Cancel subscription"
        cancelLabel="Keep"
        onConfirm={() =>
          new Promise<void>((done) => {
            resolve = done;
          })
        }
      />,
    );

    await user.click(screen.getByRole("button", { name: "Cancel subscription" }));
    expect(screen.getByRole("button", { name: "Cancel subscription" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Keep" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(onOpenChange).not.toHaveBeenCalled();

    resolve();

    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("stays open when the confirmation fails", async () => {
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        title="Retry?"
        description="Try the payment again."
        onConfirm={() => Promise.reject(new Error("failed"))}
        trigger={<Button>Retry payment</Button>}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Retry payment" }));
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
    });
    expect(screen.getByRole("alertdialog", { name: "Retry?" })).toBeInTheDocument();
  });
});
