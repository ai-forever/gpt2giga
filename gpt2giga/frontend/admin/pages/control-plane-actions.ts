import type { AdminApp } from "../app.js";
import type { PageId } from "../types.js";
import {
  describePersistOutcome,
  withBusyState,
} from "../forms.js";
import { toErrorMessage } from "../utils.js";

export type InlineStatus = {
  tone: "info" | "warn" | "danger";
  message: string;
};

export function getSubmitterButton(
  event: SubmitEvent,
  form: HTMLFormElement,
): HTMLButtonElement | null {
  const submitter = event.submitter;
  return submitter instanceof HTMLButtonElement
    ? submitter
    : form.querySelector<HTMLButtonElement>('button[type="submit"]');
}

export async function persistControlPlaneSection(options: {
  app: AdminApp;
  form: HTMLFormElement;
  button: HTMLButtonElement | null;
  endpoint: string;
  payload: Record<string, unknown>;
  refreshStatus: () => void;
  setActionState: (state: InlineStatus) => void;
  pendingMessage: string;
  pendingLabel?: string;
  outcomeLabel: string;
  failurePrefix: string;
  rerenderPage: PageId;
}): Promise<void> {
  const pendingState: InlineStatus = {
    tone: "info",
    message: options.pendingMessage,
  };
  options.setActionState(pendingState);
  options.refreshStatus();

  try {
    await withBusyState({
      root: options.form,
      button: options.button,
      pendingLabel: options.pendingLabel ?? "Saving…",
      action: async () => {
        const response = await options.app.api.json<Record<string, unknown>>(
          options.endpoint,
          {
            method: "PUT",
            json: options.payload,
          },
        );
        const outcome = describePersistOutcome(options.outcomeLabel, response);
        options.app.queueAlert(outcome.message, outcome.tone);
        await options.app.render(options.rerenderPage);
      },
    });
  } catch (error) {
    const failureState: InlineStatus = {
      tone: "danger",
      message: `${options.failurePrefix}: ${toErrorMessage(error)}`,
    };
    options.setActionState(failureState);
    options.refreshStatus();
    options.app.pushAlert(failureState.message, "danger");
  }
}

export async function testGigachatConnection(options: {
  app: AdminApp;
  form: HTMLFormElement;
  button: HTMLButtonElement | null;
  payload: Record<string, unknown>;
  refreshStatus: () => void;
  setActionState: (state: InlineStatus) => void;
  pendingMessage: string;
}): Promise<void> {
  const pendingState: InlineStatus = {
    tone: "info",
    message: options.pendingMessage,
  };
  options.setActionState(pendingState);
  options.refreshStatus();

  try {
    await withBusyState({
      root: options.form,
      button: options.button,
      pendingLabel: "Testing…",
      action: async () => {
        const result = await options.app.api.json<Record<string, unknown>>(
          "/admin/api/settings/gigachat/test",
          {
            method: "POST",
            json: options.payload,
          },
        );
        const nextState = result.ok
          ? buildGigachatTestSuccessState(result)
          : buildGigachatTestFailureState(result);
        options.setActionState(nextState);
        options.refreshStatus();
        options.app.pushAlert(nextState.message, nextState.tone);
      },
    });
  } catch (error) {
    const failureState: InlineStatus = {
      tone: "danger",
      message: `GigaChat connection test failed: ${toErrorMessage(error)}`,
    };
    options.setActionState(failureState);
    options.refreshStatus();
    options.app.pushAlert(failureState.message, "danger");
  }
}

function buildGigachatTestSuccessState(
  result: Record<string, unknown>,
): InlineStatus {
  return {
    tone: "info",
    message: `Connection ok. Models visible: ${String(result.model_count ?? 0)}. Candidate values were tested but not persisted.`,
  };
}

function buildGigachatTestFailureState(
  result: Record<string, unknown>,
): InlineStatus {
  return {
    tone: "danger",
    message: `Connection failed: ${String(result.error_type ?? "Error")}: ${String(result.error ?? "unknown error")}. Persisted values remain unchanged.`,
  };
}
