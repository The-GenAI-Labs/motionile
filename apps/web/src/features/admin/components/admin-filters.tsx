"use client";

import { SearchIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAdminFilters } from "@/features/admin/hooks/use-admin-filters";

export function AdminFilters() {
  const [filters, setFilters] = useAdminFilters();
  return (
    <section
      aria-label="Filters"
      className="grid gap-3 rounded-xl border bg-surface p-4 md:grid-cols-5"
    >
      <div className="md:col-span-2">
        <Label htmlFor="admin-search">Search</Label>
        <div className="relative mt-1">
          <SearchIcon
            aria-hidden="true"
            className="absolute top-2.5 left-3 size-4 text-muted-foreground"
          />
          <Input
            id="admin-search"
            value={filters.q}
            onChange={(event) => void setFilters({ q: event.target.value || null })}
            className="pl-9"
            placeholder="Name, email or phone"
          />
        </div>
      </div>
      <div>
        <Label htmlFor="admin-status">Status</Label>
        <Input
          id="admin-status"
          value={filters.status}
          onChange={(event) => void setFilters({ status: event.target.value || null })}
          className="mt-1"
          placeholder="Status"
        />
      </div>
      <div>
        <Label htmlFor="admin-role">Role</Label>
        <Input
          id="admin-role"
          value={filters.role}
          onChange={(event) => void setFilters({ role: event.target.value || null })}
          className="mt-1"
          placeholder="Role"
        />
      </div>
      <div className="flex items-end">
        <Button type="button" variant="outline" onClick={() => void setFilters(null)}>
          <XIcon aria-hidden="true" /> Clear filters
        </Button>
      </div>
    </section>
  );
}
