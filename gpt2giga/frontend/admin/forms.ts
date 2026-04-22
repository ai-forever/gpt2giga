import { INVALID_JSON, type SecretFieldState } from "./forms-types.js";
import { parseCsv } from "./utils.js";

export { INVALID_JSON } from "./forms-types.js";
export type {
  PendingDiffSection,
  PersistOutcomeDescriptor,
  PlannedApplyState,
  RuntimeImpactDescriptor,
  SecretFieldState,
} from "./forms-types.js";
export {
  buildApplicationPayload,
  buildObservabilityPayload,
  buildSecurityPayload,
  collectGigachatPayload,
} from "./forms-payloads.js";
export {
  buildObservabilityDiffEntries,
  buildPendingDiffEntries,
  describePendingRuntimeImpact,
  describePersistOutcome,
  planPendingApply,
  summarizePendingChanges,
} from "./forms-diff.js";

const FORM_CONTROL_SELECTOR = "button, input, select, textarea";

type FormControlElement =
  | HTMLButtonElement
  | HTMLInputElement
  | HTMLSelectElement
  | HTMLTextAreaElement;

interface ValidationOptions {
  report?: boolean;
}

interface SecretFieldBindingOptions {
  form: HTMLFormElement;
  fieldName: string;
  clearFieldName: string;
  preview: string;
}

interface ReplaceableFieldBindingOptions extends SecretFieldBindingOptions {
  clearPlaceholder: string;
  noteReplace: string;
  noteClear: string;
  noteKeep: string;
  messageReplace: string;
  messageClear: string;
  messageKeep: string;
}

export function bindValidityReset(
  ...fields: Array<FormControlElement | null | undefined>
): void {
  fields.forEach((field) => {
    if (!field) {
      return;
    }
    const resetValidity = () => {
      field.setCustomValidity("");
    };
    field.addEventListener("input", resetValidity);
    field.addEventListener("change", resetValidity);
  });
}

export function validateRequiredCsvField(
  field: HTMLInputElement | null | undefined,
  message: string,
  options?: ValidationOptions,
): string {
  if (!field) {
    return "";
  }
  const error = parseCsv(field.value).length > 0 ? "" : message;
  field.setCustomValidity(error);
  if (error && options?.report) {
    field.reportValidity();
  }
  return error;
}

export function validatePositiveNumberField(
  field: HTMLInputElement | null | undefined,
  message: string,
  options?: ValidationOptions,
): string {
  if (!field) {
    return "";
  }
  const rawValue = field.value.trim();
  let error = "";
  if (rawValue) {
    const numeric = Number(rawValue);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      error = message;
    }
  }
  field.setCustomValidity(error);
  if (error && options?.report) {
    field.reportValidity();
  }
  return error;
}

export function validateJsonArrayField(
  field: HTMLTextAreaElement | null | undefined,
  value: unknown,
  {
    invalidMessage,
    nonArrayMessage,
    report,
  }: {
    invalidMessage: string;
    nonArrayMessage: string;
    report?: boolean;
  },
): string {
  if (!field) {
    return "";
  }
  const error =
    value === INVALID_JSON
      ? invalidMessage
      : !Array.isArray(value)
        ? nonArrayMessage
        : "";
  field.setCustomValidity(error);
  if (error && report) {
    field.reportValidity();
  }
  return error;
}

export function validateJsonObjectField(
  field: HTMLTextAreaElement | null | undefined,
  value: unknown,
  {
    invalidMessage,
    nonObjectMessage,
    report,
  }: {
    invalidMessage: string;
    nonObjectMessage: string;
    report?: boolean;
  },
): string {
  if (!field) {
    return "";
  }
  const error =
    value === INVALID_JSON
      ? invalidMessage
      : value !== null &&
          (!value || typeof value !== "object" || Array.isArray(value))
        ? nonObjectMessage
        : "";
  field.setCustomValidity(error);
  if (error && report) {
    field.reportValidity();
  }
  return error;
}

export function bindReplaceableFieldBehavior(
  options: ReplaceableFieldBindingOptions,
): () => SecretFieldState | null {
  const field = options.form.elements.namedItem(options.fieldName);
  const clearToggle = options.form.elements.namedItem(options.clearFieldName);
  if (
    !(
      field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement
    ) ||
    !(clearToggle instanceof HTMLInputElement)
  ) {
    return () => null;
  }

  const note = field.closest(".stack")?.querySelector<HTMLElement>(".field-note");
  const originalPlaceholder = field.placeholder;
  const preview = options.preview || "not configured";

  const sync = (): SecretFieldState => {
    const hasValue = field.value.trim().length > 0;
    if (hasValue) {
      clearToggle.checked = false;
      clearToggle.disabled = true;
      field.disabled = false;
      field.placeholder = originalPlaceholder;
      if (note) {
        note.textContent = `Stored: ${preview}. Save: ${options.noteReplace}`;
      }
      return {
        intent: "replace",
        message: options.messageReplace,
      };
    }

    clearToggle.disabled = false;
    if (clearToggle.checked) {
      field.disabled = true;
      field.placeholder = options.clearPlaceholder;
      if (note) {
        note.textContent = `Stored: ${preview}. Save: ${options.noteClear}`;
      }
      return {
        intent: "clear",
        message: options.messageClear,
      };
    }

    field.disabled = false;
    field.placeholder = originalPlaceholder;
    if (note) {
      note.textContent = `Stored: ${preview}. Save: ${options.noteKeep}`;
    }
    return {
      intent: "keep",
      message: options.messageKeep,
    };
  };

  field.addEventListener("input", sync);
  clearToggle.addEventListener("change", sync);
  return sync;
}

export function bindSecretFieldBehavior(
  options: SecretFieldBindingOptions,
): () => SecretFieldState | null {
  return bindReplaceableFieldBehavior({
    ...options,
    clearPlaceholder: "Uncheck clear to paste a replacement secret",
    noteReplace: "replace it.",
    noteClear: "clear it.",
    noteKeep: "keep it.",
    messageReplace: "A new secret is staged and will replace the stored value on save.",
    messageClear: "The stored secret will be removed when this section is saved.",
    messageKeep: "The stored secret remains unchanged unless you paste a replacement.",
  });
}

export async function withBusyState<T>({
  root,
  button,
  pendingLabel,
  action,
}: {
  root?: Element | DocumentFragment | null;
  button?: HTMLButtonElement | null;
  pendingLabel: string;
  action: () => Promise<T>;
}): Promise<T> {
  const controls = root
    ? Array.from(root.querySelectorAll<FormControlElement>(FORM_CONTROL_SELECTOR))
    : button
      ? [button]
      : [];
  const controlStates = controls.map((control) => ({
    control,
    disabled: control.disabled,
  }));
  const originalLabel = button?.textContent ?? "";
  const busyRoot = root instanceof HTMLElement ? root : null;

  controlStates.forEach(({ control }) => {
    control.disabled = true;
  });
  if (busyRoot) {
    busyRoot.setAttribute("data-busy", "true");
    busyRoot.setAttribute("aria-busy", "true");
  }
  if (button) {
    button.textContent = pendingLabel;
    button.setAttribute("aria-busy", "true");
  }

  try {
    return await action();
  } finally {
    controlStates.forEach(({ control, disabled }) => {
      control.disabled = disabled;
    });
    if (busyRoot) {
      busyRoot.removeAttribute("data-busy");
      busyRoot.removeAttribute("aria-busy");
    }
    if (button) {
      button.textContent = originalLabel;
      button.removeAttribute("aria-busy");
    }
  }
}
