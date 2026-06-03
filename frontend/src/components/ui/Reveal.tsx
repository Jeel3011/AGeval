"use client";

import React, { useEffect, useRef, useState } from "react";

/**
 * Scroll-reveal wrapper. Children rise + fade in the first time they enter the
 * viewport. Monochrome-friendly, respects prefers-reduced-motion (handled in
 * globals.css). Use `delay` to stagger siblings and `variant` for direction.
 */
export function Reveal({
  children,
  delay = 0,
  variant,
  as: Tag = "div",
  className = "",
  once = true,
  ...rest
}: {
  children: React.ReactNode;
  delay?: number;
  variant?: "left" | "scale";
  as?: keyof JSX.IntrinsicElements;
  className?: string;
  once?: boolean;
} & React.HTMLAttributes<HTMLElement>) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          if (once) io.disconnect();
        } else if (!once) {
          setShown(false);
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [once]);

  const variantClass = variant === "left" ? "reveal-left" : variant === "scale" ? "reveal-scale" : "";

  return React.createElement(
    Tag as any,
    {
      ref: ref as any,
      className: `reveal ${variantClass} ${shown ? "is-in" : ""} ${className}`.trim(),
      style: { ["--d" as any]: `${delay}ms`, ...(rest.style || {}) },
      ...rest,
    },
    children,
  );
}
