import Link from "next/link";

import { SiteLogo } from "@/components/layouts/site-logo";
import { footerNavigation } from "@/config/navigation";
import { siteConfig } from "@/config/site";

export function PublicFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto grid w-full max-w-6xl gap-10 px-6 py-12 md:grid-cols-[2fr_repeat(3,1fr)]">
        <div className="flex flex-col gap-3">
          <SiteLogo />
          <p className="max-w-xs text-sm text-muted-foreground">{siteConfig.tagline}</p>
        </div>
        {footerNavigation.map((group) => (
          <nav key={group.title} aria-label={group.title}>
            <h2 className="text-sm font-medium">{group.title}</h2>
            <ul className="mt-3 flex flex-col gap-2">
              {group.links.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="rounded-sm text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
                  >
                    {link.title}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="border-t">
        <p className="mx-auto w-full max-w-6xl px-6 py-6 text-xs text-muted-foreground">
          © {new Date().getFullYear()} {siteConfig.name}. Made in India.
        </p>
      </div>
    </footer>
  );
}
