export type PageId =
  | "overview"
  | "setup"
  | "settings"
  | "keys"
  | "logs"
  | "playground"
  | "traffic"
  | "providers"
  | "files-batches"
  | "system";

export type WorkflowId = "start" | "configure" | "observe" | "diagnose";

export type AlertTone = "info" | "warn" | "danger";

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export interface RouteMeta {
  eyebrow: string;
  title: string;
  subtitle: string;
  workflow: WorkflowId;
  navDescription: string;
}

export interface WorkflowMeta {
  label: string;
  description: string;
}

export interface DiffEntry {
  field: string;
  current: unknown;
  target: unknown;
}

export interface PendingChangeSummary {
  changedFields: string[];
  restartFields: string[];
  liveFields: string[];
  secretFields: string[];
}

export interface SetupStep {
  id?: string;
  label: string;
  description?: string;
  ready?: boolean;
}

export interface RuntimePayload {
  mode?: string;
  gigachat_api_mode?: string;
  gigachat_responses_api_mode?: string | null;
  chat_backend_mode?: string;
  responses_backend_mode?: string;
  enabled_providers?: string[];
  telemetry_enabled?: boolean;
  runtime_store_backend?: string;
}

export interface SetupPayload {
  persisted?: boolean;
  gigachat_ready?: boolean;
  security_ready?: boolean;
  setup_complete?: boolean;
  scoped_api_keys_configured?: number;
  global_api_key_configured?: boolean;
  path?: string;
  key_path?: string | null;
  wizard_steps?: SetupStep[];
  warnings?: string[];
  claim?: JsonObject;
  bootstrap?: JsonObject;
}

export interface SettingsSectionPayload {
  values: Record<string, unknown>;
  control_plane?: Record<string, unknown>;
  restart_required?: boolean;
  section?: string;
}

export interface KeysPayload {
  global: Record<string, unknown>;
  scoped: Record<string, unknown>[];
}

export interface AlertMessage {
  message: string;
  tone: AlertTone;
}
