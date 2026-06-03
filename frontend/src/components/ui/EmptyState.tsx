"use client";

import React from "react";

/**
 * Consistent editorial empty state. Replaces the ad-hoc dashed boxes that made
 * pages look unfinished. Large muted glyph, a clear line, optional hint/action.
 */
export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="ed-card flex flex-col items-center justify-center text-center px-6 py-20">
      {icon && (
        <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-50 border border-zinc-200 text-zinc-400">
          {icon}
        </div>
      )}
      <div className="text-[15px] font-medium text-zinc-700">{title}</div>
      {hint && <p className="mt-1.5 text-sm text-zinc-400 max-w-sm leading-relaxed">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/** Shared padded page container so every dashboard page aligns identically. */
export function PageContainer({ children }: { children: React.ReactNode }) {
  return <div className="px-8 py-8 max-w-[1180px] mx-auto w-full">{children}</div>;
}
