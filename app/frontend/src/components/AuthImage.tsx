"use client";

import { useState, useEffect, useRef } from "react";
import { authedUrl } from "@/hooks/useApi";

interface AuthImageProps {
  src: string;
  alt: string;
  className?: string;
  fallback?: React.ReactNode;
  /** If true, loads immediately without waiting to enter viewport (default: false) */
  eager?: boolean;
}

/**
 * Image component that uses ?token= auth in the URL.
 * Uses IntersectionObserver for lazy loading.
 */
export default function AuthImage({ src, alt, className, fallback, eager = false }: AuthImageProps) {
  const [failed, setFailed] = useState(false);
  const [inView, setInView] = useState(eager);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Lazy load: observe when element enters viewport
  useEffect(() => {
    if (eager || inView) return;
    const el = containerRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [eager, inView]);

  if (failed) return <>{fallback ?? null}</>;

  if (!inView) {
    return (
      <div
        ref={containerRef}
        className={className}
        style={{ background: "var(--bg-hover)" }}
      />
    );
  }

  return (
    <img
      src={authedUrl(src)}
      alt={alt}
      className={className}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
