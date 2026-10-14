import { useQueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Providers } from "@/app/providers";
import { getQueryClient } from "@/lib/query/query-client";

function QueryClientProbe() {
  const client = useQueryClient();
  return <p>{client === getQueryClient() ? "shared client" : "other client"}</p>;
}

describe("Providers", () => {
  it("provides the browser query client and a toaster", () => {
    render(
      <Providers>
        <QueryClientProbe />
      </Providers>,
    );

    expect(screen.getByText("shared client")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Notifications/ })).toBeInTheDocument();
  });
});
