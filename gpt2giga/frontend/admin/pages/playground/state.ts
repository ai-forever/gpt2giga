export type SurfaceId =
  | "openai-chat"
  | "openai-responses"
  | "anthropic-messages"
  | "gemini-generate";

export type RunPhase = "idle" | "sending" | "streaming" | "success" | "error" | "aborted";

export interface PlaygroundRequest {
  surface: SurfaceId;
  label: string;
  url: string;
  stream: boolean;
  authLabel: string;
  body: Record<string, unknown>;
}

export interface PlaygroundPreset {
  id: string;
  label: string;
  description: string;
  surface: SurfaceId;
  model: string;
  systemPrompt: string;
  userPrompt: string;
  stream: boolean;
}

export interface PlaygroundRunState {
  phase: RunPhase;
  note: string;
  request: PlaygroundRequest | null;
  startedAt: number | null;
  finishedAt: number | null;
  statusCode: number | null;
  statusText: string;
  contentType: string;
  bytesReceived: number;
  chunkCount: number;
  eventCount: number;
  assistantOutput: string;
  rawOutput: string;
  errorText: string;
}

export interface ParsedSseEvent {
  type: string;
  data: string;
}

export interface PlaygroundPageState {
  activeController: AbortController | null;
  activeRunId: number;
  runState: PlaygroundRunState;
  streamEvents: ParsedSseEvent[];
}

export interface PlaygroundFormFields extends HTMLFormControlsCollection {
  surface: HTMLSelectElement;
  model: HTMLInputElement;
  system_prompt: HTMLTextAreaElement;
  user_prompt: HTMLTextAreaElement;
  stream: HTMLSelectElement;
}

export const DEFAULT_OUTPUT = "No request yet.";
export const DEFAULT_ASSISTANT_OUTPUT = "Assistant output will appear here.";

export const PLAYGROUND_PRESETS: PlaygroundPreset[] = [
  {
    id: "openai-chat-hello",
    label: "OpenAI hello",
    description: "Fast non-stream smoke for the default OpenAI-compatible chat route.",
    surface: "openai-chat",
    model: "GigaChat",
    systemPrompt: "You are concise and answer in one short sentence.",
    userPrompt: "Привет! Ответь одной фразой, что gateway отвечает.",
    stream: false,
  },
  {
    id: "openai-chat-stream",
    label: "OpenAI stream",
    description: "Verifies SSE lifecycle and final completion handling on chat/completions.",
    surface: "openai-chat",
    model: "GigaChat",
    systemPrompt: "You are concise.",
    userPrompt: "Расскажи в двух коротких предложениях, что этот stream живой.",
    stream: true,
  },
  {
    id: "openai-responses",
    label: "Responses API",
    description: "Exercises the newer responses surface with instructions and unified output.",
    surface: "openai-responses",
    model: "GigaChat",
    systemPrompt: "Answer as a terse operations assistant.",
    userPrompt: "Summarize why this proxy is useful in one sentence.",
    stream: false,
  },
  {
    id: "anthropic-messages",
    label: "Anthropic messages",
    description: "Smoke-checks the Anthropic-compatible router with a familiar payload shape.",
    surface: "anthropic-messages",
    model: "GigaChat",
    systemPrompt: "You are concise.",
    userPrompt: "Say hello from the Anthropic-compatible surface.",
    stream: false,
  },
  {
    id: "gemini-stream",
    label: "Gemini stream",
    description: "Targets Gemini-compatible SSE and uses proper systemInstruction mapping.",
    surface: "gemini-generate",
    model: "gemini-test",
    systemPrompt: "Be brief.",
    userPrompt: "Write a short stream smoke response.",
    stream: true,
  },
];

export const DEFAULT_PLAYGROUND_PRESET = PLAYGROUND_PRESETS[0]!;

export function createIdleRunState(): PlaygroundRunState {
  return {
    phase: "idle",
    note: DEFAULT_OUTPUT,
    request: null,
    startedAt: null,
    finishedAt: null,
    statusCode: null,
    statusText: "",
    contentType: "",
    bytesReceived: 0,
    chunkCount: 0,
    eventCount: 0,
    assistantOutput: "",
    rawOutput: "",
    errorText: "",
  };
}

export function createPlaygroundPageState(): PlaygroundPageState {
  return {
    activeController: null,
    activeRunId: 0,
    runState: createIdleRunState(),
    streamEvents: [],
  };
}

export function getPlaygroundFields(form: HTMLFormElement): PlaygroundFormFields {
  return form.elements as PlaygroundFormFields;
}
