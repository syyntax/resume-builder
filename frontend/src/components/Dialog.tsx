import { X } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef } from "react";

import { Button } from "./ui";

interface DialogProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
  busy?: boolean;
  confirmDisabled?: boolean;
  /** Omit for an informational dialog with a single Close button. */
  onConfirm?: () => void;
  onClose: () => void;
}

/** Accessible modal built on the native <dialog> element (focus trap and Esc come for free). */
export function Dialog({
  open,
  title,
  description,
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "primary",
  busy = false,
  confirmDisabled = false,
  onConfirm,
  onClose,
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-xl border border-slate-200 bg-white p-0 text-slate-900 shadow-xl dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100"
    >
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (onConfirm) onConfirm();
          else onClose();
        }}
      >
        <div className="flex items-start justify-between gap-4 px-5 pt-5">
          <div>
            <h2 id={titleId} className="text-base font-semibold">
              {title}
            </h2>
            {description && <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</div>}
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
            aria-label="Close"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>
        {children && <div className="space-y-4 px-5 pt-4">{children}</div>}
        <div className="mt-5 flex justify-end gap-2 border-t border-slate-200 px-5 py-4 dark:border-slate-800">
          {onConfirm ? (
            <>
              <Button variant="secondary" onClick={onClose} disabled={busy}>
                {cancelLabel}
              </Button>
              <Button type="submit" variant={tone === "danger" ? "danger" : "primary"} loading={busy} disabled={confirmDisabled}>
                {confirmLabel}
              </Button>
            </>
          ) : (
            <Button type="submit">Close</Button>
          )}
        </div>
      </form>
    </dialog>
  );
}
