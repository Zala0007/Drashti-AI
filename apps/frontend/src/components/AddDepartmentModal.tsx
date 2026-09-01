import type { Department } from "../types/registry";
import { DepartmentCreatePanel } from "./DepartmentCreatePanel";
import { Modal } from "./Modal";

interface AddDepartmentModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (department: Department) => void;
}

export function AddDepartmentModal({ open, onClose, onCreated }: AddDepartmentModalProps) {
  return (
    <Modal open={open} onClose={onClose} title="Add department" eyebrow="Registry administration">
      <div className="modal__body">
        <DepartmentCreatePanel onCancel={onClose} onCreated={(department) => { onCreated(department); onClose(); }} />
      </div>
    </Modal>
  );
}
