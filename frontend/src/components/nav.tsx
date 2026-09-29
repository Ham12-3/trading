"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/feed", label: "Feed" },
  { href: "/events", label: "Event study" },
  { href: "/backtest", label: "Backtest" },
  { href: "/models", label: "Models" },
  { href: "/about", label: "About" },
] as const;

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="-mx-1 flex gap-1 overflow-x-auto text-sm">
      {LINKS.map(({ href, label }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md border px-2.5 py-1 whitespace-nowrap ${
              active
                ? "bg-surface text-fg border-border"
                : "text-muted hover:text-fg border-transparent"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
