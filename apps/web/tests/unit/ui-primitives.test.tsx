import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Toaster } from "@/components/ui/sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

describe("ui primitives", () => {
  it("toggles a labelled checkbox", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(
      <div>
        <Checkbox id="consent" onCheckedChange={onCheckedChange} />
        <Label htmlFor="consent">I consent to voice cloning</Label>
      </div>,
    );

    const checkbox = screen.getByRole("checkbox", { name: "I consent to voice cloning" });
    await user.click(checkbox);

    expect(checkbox).toBeChecked();
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it("switches tabs with the keyboard", async () => {
    const user = userEvent.setup();
    render(
      <Tabs defaultValue="video">
        <TabsList aria-label="Format">
          <TabsTrigger value="video">Video</TabsTrigger>
          <TabsTrigger value="short">Short</TabsTrigger>
        </TabsList>
        <TabsContent value="video">Landscape</TabsContent>
        <TabsContent value="short">Portrait</TabsContent>
      </Tabs>,
    );

    await user.click(screen.getByRole("tab", { name: "Video" }));
    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("tab", { name: "Short" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Short" })).toHaveTextContent("Portrait");
  });

  it("opens a dialog with a title and description", async () => {
    const user = userEvent.setup();
    render(
      <Dialog>
        <DialogTrigger>Open details</DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Render details</DialogTitle>
            <DialogDescription>Formats and duration.</DialogDescription>
          </DialogHeader>
          <DialogFooter showCloseButton />
        </DialogContent>
      </Dialog>,
    );

    await user.click(screen.getByRole("button", { name: "Open details" }));
    const dialog = screen.getByRole("dialog", { name: "Render details" });
    expect(dialog).toHaveAccessibleDescription("Formats and duration.");
    expect(within(dialog).getAllByRole("button", { name: "Close" })).toHaveLength(2);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens a sheet from either side", async () => {
    const user = userEvent.setup();
    render(
      <Sheet>
        <SheetTrigger>Filters</SheetTrigger>
        <SheetContent side="bottom">
          <SheetHeader>
            <SheetTitle>Filters</SheetTitle>
            <SheetDescription>Narrow the list.</SheetDescription>
          </SheetHeader>
          <SheetFooter>Footer</SheetFooter>
        </SheetContent>
      </Sheet>,
    );

    await user.click(screen.getByRole("button", { name: "Filters" }));

    expect(screen.getByRole("dialog", { name: "Filters" })).toHaveAccessibleDescription(
      "Narrow the list.",
    );
  });

  it("opens a dropdown menu with items, checkboxes, radios and submenus", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Actions</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuLabel>Video</DropdownMenuLabel>
          <DropdownMenuGroup>
            <DropdownMenuItem onSelect={onSelect}>
              Rename
              <DropdownMenuShortcut>R</DropdownMenuShortcut>
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive">Delete</DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuCheckboxItem checked>Subtitles</DropdownMenuCheckboxItem>
          <DropdownMenuRadioGroup value="16:9">
            <DropdownMenuRadioItem value="16:9">Landscape</DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="9:16">Portrait</DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>Share</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem>Copy link</DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        </DropdownMenuContent>
      </DropdownMenu>,
    );

    await user.click(screen.getByRole("button", { name: "Actions" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitemcheckbox", { name: "Subtitles" })).toBeChecked();
    expect(within(menu).getByRole("menuitemradio", { name: "Landscape" })).toBeChecked();
    expect(within(menu).getByRole("menuitem", { name: "Share" })).toHaveAttribute(
      "aria-haspopup",
      "menu",
    );

    await user.click(within(menu).getByRole("menuitem", { name: /^Rename/ }));
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("renders a labelled select trigger", () => {
    render(
      <Select defaultValue="en">
        <SelectTrigger aria-label="Narration language">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Languages</SelectLabel>
            <SelectItem value="en">English</SelectItem>
            <SelectSeparator />
            <SelectItem value="hi">Hindi</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>,
    );

    expect(screen.getByRole("combobox", { name: "Narration language" })).toHaveTextContent(
      "English",
    );
  });

  it("shows a tooltip on keyboard focus", async () => {
    const user = userEvent.setup();
    render(
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger>Credits</TooltipTrigger>
          <TooltipContent>Credits left this month</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );

    await user.tab();

    expect(await screen.findByRole("tooltip")).toHaveTextContent("Credits left this month");
  });

  it("renders static primitives", () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Starter</CardTitle>
          <CardDescription>For new creators</CardDescription>
          <CardAction>
            <Badge variant="success">Active</Badge>
          </CardAction>
        </CardHeader>
        <CardContent>
          <Avatar>
            <AvatarFallback>AB</AvatarFallback>
          </Avatar>
          <Separator />
          <Skeleton className="h-4" />
          <Table aria-label="Usage">
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell>Render</TableCell>
              </TableRow>
            </TableBody>
            <TableFooter>
              <TableRow>
                <TableCell>Total</TableCell>
              </TableRow>
            </TableFooter>
          </Table>
        </CardContent>
        <CardFooter>
          <Badge asChild variant="outline">
            <a href="#plans">Compare plans</a>
          </Badge>
        </CardFooter>
      </Card>,
    );

    expect(screen.getByText("Starter")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("AB")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Usage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Compare plans" })).toHaveAttribute("href", "#plans");
  });

  it("announces toasts", async () => {
    render(<Toaster />);

    act(() => {
      toast.success("Video published");
    });

    expect(await screen.findByText("Video published")).toBeInTheDocument();
  });
});
