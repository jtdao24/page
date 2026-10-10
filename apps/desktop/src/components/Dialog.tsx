import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef } from "react";

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface DialogProps {
  title: string;
  /** Escape and the Cancel button call this; it never discards content. */
  onCancel: () => void;
  children: ReactNode;
  tone?: "default" | "danger";
}

/** Modal dialog with focus containment and focus restoration on close. */
export function Dialog({ title, onCancel, children, tone = "default" }: DialogProps) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const cancel = useRef(onCancel);
  useEffect(() => {
    cancel.current = onCancel;
  });

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = panel.current?.querySelector<HTMLElement>("[data-autofocus]") ??
      panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    return () => {
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      cancel.current();
      return;
    }
    if (event.key !== "Tab" || panel.current === null) return;
    const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKeyDown}
        className={`dialog-panel max-h-full w-full max-w-lg overflow-auto rounded-lg p-5 shadow-xl ${
          tone === "danger" ? "border border-red-300" : ""
        }`}
      >
        <h2 id={titleId} className="mb-3 text-base font-semibold">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
