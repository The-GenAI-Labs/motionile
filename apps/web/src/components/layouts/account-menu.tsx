"use client";

import { CreditCard, Home, LayoutDashboard, Settings, Shield } from "lucide-react";
import Link from "next/link";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { AppArea } from "@/config/navigation";
import { LogoutButton } from "@/features/auth/components/logout-button";
import { useCurrentUser } from "@/features/auth/hooks/use-current-user";

interface AccountMenuProps {
  area: AppArea;
}

export function AccountMenu({ area }: AccountMenuProps) {
  const user = useCurrentUser();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="rounded-full" aria-label="Account menu">
          <Avatar size="sm">
            <AvatarFallback>
              <span aria-hidden="true">M</span>
            </AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>{user.data?.name ?? "Account"}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {area === "admin" ? (
          <DropdownMenuItem asChild>
            <Link href={{ pathname: "/dashboard" }}>
              <LayoutDashboard aria-hidden="true" />
              Workspace
            </Link>
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem asChild>
            <Link href={{ pathname: "/admin" }}>
              <Shield aria-hidden="true" />
              Admin console
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuItem asChild>
          <Link href={{ pathname: "/billing" }}>
            <CreditCard aria-hidden="true" />
            Billing
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={{ pathname: "/settings/security" }}>
            <Settings aria-hidden="true" />
            Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/">
            <Home aria-hidden="true" />
            Back to site
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <LogoutButton menuItem />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
