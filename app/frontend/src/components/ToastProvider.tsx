"use client";

/**
 * Compatibility wrapper around Sonner.
 * Preserves the existing useToast() API so pages work without changes.
 * During page migration, switch to `import { toast } from "sonner"` directly.
 */

import { toast as sonnerToast } from "sonner";

type ToastType = "success" | "error" | "info";

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
}

export function useToast(): ToastContextValue {
  return {
    toast: (message: string, type: ToastType = "info") => {
      switch (type) {
        case "success":
          sonnerToast.success(message);
          break;
        case "error":
          sonnerToast.error(message);
          break;
        default:
          sonnerToast.info(message);
          break;
      }
    },
  };
}

/**
 * @deprecated — Sonner <Toaster /> is now rendered in ClientShell.
 * This component is kept for import compatibility only.
 */
export default function ToastProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
