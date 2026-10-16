"use client";
import { Button } from "@/components/ui/button";
import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { authErrorMessage } from "@/features/auth/errors";
import { useLogout } from "@/features/auth/hooks/use-auth-mutations";
export function LogoutButton({ menuItem = false }: { menuItem?: boolean }) {
  const logout = useLogout();
  return (
    <>
      {menuItem ? (
        <DropdownMenuItem
          disabled={logout.isPending}
          onSelect={() => {
            logout.mutate();
          }}
        >
          Sign out
        </DropdownMenuItem>
      ) : (
        <Button
          variant="ghost"
          disabled={logout.isPending}
          onClick={() => {
            logout.mutate();
          }}
        >
          Sign out
        </Button>
      )}
      {logout.error ? <p role="alert">{authErrorMessage(logout.error)}</p> : null}
    </>
  );
}
