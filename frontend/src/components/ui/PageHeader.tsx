"use client";

import React from "react";

/**
 * The shared editorial page header used on every dashboard page.
 * Kicker (eyebrow) + bold display title + lede, with optional right-aligned
 * actions, sitting above a strong editorial rule. Monochrome by design.
 */
export function PageHeader({
  kicker,
  title,
  lede,
  actions,
}: {
  kicker?: string;
  title: string;
  lede?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-8">
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div className="min-w-0">
          {kicker && <div className="ed-kicker mb-2">{kicker}</div>}
          <h1 className="ed-display text-[2rem] md:text-[2.5rem] text-zinc-900">{title}</h1>
          {lede && (
            <p className="mt-2 text-[15px] text-zinc-500 max-w-2xl leading-relaxed">{lede}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      <div className="ed-rule mt-6" />
    </header>
  );
}
