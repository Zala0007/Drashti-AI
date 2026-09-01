import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

interface ModalProps {
  open: boolean;
  title: string;
  eyebrow?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  busy?: boolean;
}

export function Modal({ open, title, eyebrow, children, onClose, wide = false, busy = false }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
    };
  }, [busy, onClose, open]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={() => { if (!busy) onClose(); }}>
      <section
        aria-labelledby="modal-title"
        aria-modal="true"
        className={`modal${wide ? " modal--wide" : ""}`}
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal__header">
          <div>{eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}<h2 id="modal-title">{title}</h2></div>
          <button type="button" aria-label="Close dialog" onClick={onClose} disabled={busy}><X aria-hidden="true" size={20} /></button>
        </header>
        {children}
      </section>
    </div>
  );
}
