import type { Route } from "next";
import Link from "next/link";

import { type BreadcrumbItem, buildBreadcrumbListJsonLd, JsonLd } from "@/lib/seo/json-ld";

export function CatalogBreadcrumbs({ items }: { items: readonly BreadcrumbItem[] }) {
  return (
    <>
      <nav aria-label="Breadcrumb">
        <ol className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          {items.map((item, index) => (
            <li key={item.path} className="flex items-center gap-2">
              {index > 0 ? <span aria-hidden="true">/</span> : null}
              {index === items.length - 1 ? (
                <span aria-current="page" className="text-foreground">
                  {item.name}
                </span>
              ) : (
                <Link href={item.path as Route} className="hover:text-foreground">
                  {item.name}
                </Link>
              )}
            </li>
          ))}
        </ol>
      </nav>
      <JsonLd data={buildBreadcrumbListJsonLd(items)} />
    </>
  );
}
