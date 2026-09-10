"use client";

// In-app replacements for window.confirm and window.prompt: the browser's own
// boxes cannot be styled, cannot say which button is the dangerous one, and
// look like a different application stopped by to ask.

import { useId, useState, type ReactNode } from "react";

import Button from "./Button";
import Field from "./Field";
import Modal, { ModalFooter } from "./Modal";
import { TextArea } from "./TextInput";
import styles from "./ConfirmDialog.module.css";

export interface ConfirmDialogProps {
  title: string;
  /** What will happen, in a sentence or two. */
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** `danger` for anything that removes or disconnects. */
  tone?: "primary" | "danger";
  isBusy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Asks before doing something. Focus starts on Cancel, so a stray Enter never
 * confirms a destructive action.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "primary",
  isBusy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal title={title} size="sm" onClose={onCancel}>
      {children ? <div className={styles.body}>{children}</div> : null}
      <ModalFooter className={styles.footer}>
        <Button onClick={onCancel} disabled={isBusy} autoFocus>
          {cancelLabel}
        </Button>
        <Button variant={tone} onClick={onConfirm} disabled={isBusy}>
          {confirmLabel}
        </Button>
      </ModalFooter>
    </Modal>
  );
}

export interface PromptDialogProps {
  title: string;
  /** Label of the text field. */
  label: string;
  hint?: ReactNode;
  placeholder?: string;
  isOptional?: boolean;
  confirmLabel: string;
  tone?: "primary" | "danger";
  /** Receives the trimmed text; empty when the field was left blank. */
  onSubmit: (value: string) => void;
  onCancel: () => void;
}

/** Asks for a short piece of text (a reason, an instruction) before acting. */
export function PromptDialog({
  title,
  label,
  hint,
  placeholder,
  isOptional = true,
  confirmLabel,
  tone = "primary",
  onSubmit,
  onCancel,
}: PromptDialogProps) {
  const [value, setValue] = useState("");
  const id = useId();
  const fieldId = `${id}-field`;
  const formId = `${id}-form`;

  return (
    <Modal title={title} size="sm" onClose={onCancel}>
      <form
        id={formId}
        className={styles.body}
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(value.trim());
        }}
      >
        <Field label={label} htmlFor={fieldId} isOptional={isOptional} hint={hint}>
          <TextArea
            id={fieldId}
            controlSize="sm"
            rows={3}
            value={value}
            placeholder={placeholder}
            onChange={(event) => setValue(event.target.value)}
            autoFocus
          />
        </Field>
      </form>
      <ModalFooter className={styles.footer}>
        <Button onClick={onCancel}>Cancel</Button>
        <Button type="submit" form={formId} variant={tone}>
          {confirmLabel}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
