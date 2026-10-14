import { zodResolver } from "@hookform/resolvers/zod";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const schema = z.object({
  topic: z.string().trim().min(3, "Enter at least 3 characters"),
  notes: z.string().max(20, "Keep notes short"),
});

type Values = z.infer<typeof schema>;

function TopicForm({ onSubmit }: { onSubmit: (values: Values) => void }) {
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { topic: "", notes: "" },
  });
  return (
    <Form {...form}>
      <form
        noValidate
        onSubmit={(event) => {
          void form.handleSubmit(onSubmit)(event);
        }}
      >
        <FormField
          control={form.control}
          name="topic"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Topic</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormDescription>What should the video explain?</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="notes"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Notes</FormLabel>
              <FormControl>
                <Textarea {...field} />
              </FormControl>
              <FormMessage>Optional</FormMessage>
            </FormItem>
          )}
        />
        <Button type="submit">Create</Button>
      </form>
    </Form>
  );
}

describe("form primitives", () => {
  it("labels and describes controls", () => {
    render(<TopicForm onSubmit={vi.fn()} />);

    const topic = screen.getByRole("textbox", { name: "Topic" });
    expect(topic).toHaveAccessibleDescription("What should the video explain?");
    expect(topic).toHaveAttribute("aria-invalid", "false");
    expect(screen.getByText("Optional")).toBeInTheDocument();
  });

  it("shows zod validation errors and marks the field invalid", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<TopicForm onSubmit={onSubmit} />);

    await user.type(screen.getByRole("textbox", { name: "Topic" }), "ab");
    await user.click(screen.getByRole("button", { name: "Create" }));

    const topic = screen.getByRole("textbox", { name: "Topic" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter at least 3 characters");
    expect(topic).toHaveAttribute("aria-invalid", "true");
    expect(topic).toHaveAccessibleDescription(
      "What should the video explain? Enter at least 3 characters",
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits valid values", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<TopicForm onSubmit={onSubmit} />);

    await user.type(screen.getByRole("textbox", { name: "Topic" }), "How DNS works");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(onSubmit).toHaveBeenCalledWith({ topic: "How DNS works", notes: "" }, expect.anything());
  });

  it("requires form field context", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Orphan() {
      const form = useForm();
      return (
        <Form {...form}>
          <FormDescription>Orphan</FormDescription>
        </Form>
      );
    }

    expect(() => render(<Orphan />)).toThrow(/must be used within <FormField> and <FormItem>/);
    consoleError.mockRestore();
  });
});
