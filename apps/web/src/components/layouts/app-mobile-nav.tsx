"use client";

import { MenuIcon } from "lucide-react";
import { useState } from "react";

import { SidebarNav } from "@/components/layouts/sidebar-nav";
import { SiteLogo } from "@/components/layouts/site-logo";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { type AppArea, appNavigation } from "@/config/navigation";

interface AppMobileNavProps {
  area: AppArea;
}

export function AppMobileNav({ area }: AppMobileNavProps) {
  const [open, setOpen] = useState(false);
  const navigation = appNavigation[area];
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          aria-label={`Open ${navigation.label.toLowerCase()} navigation`}
        >
          <MenuIcon aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left">
        <SheetHeader>
          <SheetTitle asChild>
            <div>
              <SiteLogo />
            </div>
          </SheetTitle>
          <SheetDescription className="sr-only">{navigation.label} navigation</SheetDescription>
        </SheetHeader>
        <div className="px-4">
          <SidebarNav
            area={area}
            onNavigate={() => {
              setOpen(false);
            }}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}
