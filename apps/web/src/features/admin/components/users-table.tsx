"use client";

import type { zAdminUserSummary } from "@motionile/api-contract";
import type { Route } from "next";
import Link from "next/link";
import type { z } from "zod";

import { createDataTableColumnHelper, DataTable } from "@/components/shared/data-table";
import { Badge } from "@/components/ui/badge";
import { AdminFilters } from "@/features/admin/components/admin-filters";
import { useAdminFilters } from "@/features/admin/hooks/use-admin-filters";
import { useAdminUsers } from "@/features/admin/hooks/use-admin-users";

type AdminUser = z.infer<typeof zAdminUserSummary>;
const column = createDataTableColumnHelper<AdminUser>();
const columns = [
  column.display({
    id: "name",
    header: "User",
    cell: ({ row }) => (
      <div>
        <Link
          href={`/admin/users/${row.original.id}` as Route}
          className="font-medium hover:underline"
        >
          {row.original.name ?? "Unnamed user"}
        </Link>
        <p className="text-xs text-muted-foreground">
          {row.original.primaryContact ?? "No primary contact"}
        </p>
      </div>
    ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant="outline" className="capitalize">
        {row.original.status}
      </Badge>
    ),
  }),
  column.display({
    id: "roles",
    header: "Roles",
    cell: ({ row }) => row.original.roles.join(", ") || "User",
  }),
  column.display({
    id: "createdAt",
    header: "Joined",
    cell: ({ row }) => new Date(row.original.createdAt).toLocaleDateString(),
  }),
];

export function UsersTable() {
  const [filters] = useAdminFilters();
  const query = useAdminUsers(filters);
  return (
    <div className="space-y-5">
      <AdminFilters />
      {query.isPending ? (
        <p role="status">Loading users…</p>
      ) : query.isError ? (
        <p role="alert" className="text-destructive">
          Users could not be loaded.
        </p>
      ) : (
        <DataTable
          caption="Users"
          columns={columns}
          data={query.data.items}
          getRowId={(user) => user.id}
        />
      )}
    </div>
  );
}
