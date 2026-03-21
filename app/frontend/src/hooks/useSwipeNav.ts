"use client";

import { useEffect, useRef, useCallback } from "react";
import { usePathname, useRouter } from "next/navigation";

/**
 * Page order matching the sidebar navigation.
 * Swipe RIGHT (finger moves left→right) = previous page
 * Swipe LEFT  (finger moves right→left) = next page
 */
const PAGE_ORDER = [
  "/dashboard",
  "/beats",
  "/automation",
  "/trends",
  "/dj",
  "/queue",
  "/brand",
  "/stores",
  "/social",
  "/analytics",
  "/settings",
];

const SWIPE_THRESHOLD = 80; // minimum px distance to trigger
const SWIPE_MAX_Y = 60; // max vertical movement (prevents triggering on scroll)
const SWIPE_MAX_TIME = 400; // max ms for the swipe gesture

export function useSwipeNav() {
  const pathname = usePathname();
  const router = useRouter();
  const touchRef = useRef<{
    startX: number;
    startY: number;
    startTime: number;
  } | null>(null);

  const navigate = useCallback(
    (direction: "next" | "prev") => {
      const idx = PAGE_ORDER.indexOf(pathname);
      if (idx === -1) return; // not on a navigable page

      if (direction === "next" && idx < PAGE_ORDER.length - 1) {
        router.push(PAGE_ORDER[idx + 1]);
      } else if (direction === "prev" && idx > 0) {
        router.push(PAGE_ORDER[idx - 1]);
      }
    },
    [pathname, router]
  );

  useEffect(() => {
    const onTouchStart = (e: TouchEvent) => {
      // Skip if the touch originates inside a horizontally scrollable container
      // or interactive elements that use horizontal swiping (carousels, sliders, etc.)
      const target = e.target as HTMLElement;
      if (target.closest("[data-no-swipe-nav]")) return;

      const touch = e.touches[0];
      touchRef.current = {
        startX: touch.clientX,
        startY: touch.clientY,
        startTime: Date.now(),
      };
    };

    const onTouchEnd = (e: TouchEvent) => {
      if (!touchRef.current) return;

      const touch = e.changedTouches[0];
      const deltaX = touch.clientX - touchRef.current.startX;
      const deltaY = Math.abs(touch.clientY - touchRef.current.startY);
      const elapsed = Date.now() - touchRef.current.startTime;

      touchRef.current = null;

      // Guard: too slow, too much vertical movement, or too short
      if (elapsed > SWIPE_MAX_TIME) return;
      if (deltaY > SWIPE_MAX_Y) return;
      if (Math.abs(deltaX) < SWIPE_THRESHOLD) return;

      if (deltaX > 0) {
        // Swiped RIGHT → go to previous page
        navigate("prev");
      } else {
        // Swiped LEFT → go to next page
        navigate("next");
      }
    };

    document.addEventListener("touchstart", onTouchStart, { passive: true });
    document.addEventListener("touchend", onTouchEnd, { passive: true });

    return () => {
      document.removeEventListener("touchstart", onTouchStart);
      document.removeEventListener("touchend", onTouchEnd);
    };
  }, [navigate]);
}
