export const DEFAULT_OUTPUT = "No request yet.";
export const DEFAULT_ASSISTANT_OUTPUT = "Assistant output will appear here.";
export const FALLBACK_PLAYGROUND_MODEL = "GigaChat";
export const DEFAULT_PLAYGROUND_PRESET_ID = "openai-chat-hello";
const PLAYGROUND_PRESET_DEFINITIONS = [
    {
        id: "openai-chat-hello",
        label: "OpenAI hello",
        description: "Fast non-stream smoke for the default OpenAI-compatible chat route.",
        surface: "openai-chat",
        systemPrompt: "You are concise and answer in one short sentence.",
        userPrompt: "Привет! Ответь одной фразой, что gateway отвечает.",
        stream: false,
    },
    {
        id: "openai-chat-stream",
        label: "OpenAI stream",
        description: "Verifies SSE lifecycle and final completion handling on chat/completions.",
        surface: "openai-chat",
        systemPrompt: "You are concise.",
        userPrompt: "Расскажи в двух коротких предложениях, что этот stream живой.",
        stream: true,
    },
    {
        id: "openai-responses",
        label: "Responses API",
        description: "Exercises the newer responses surface with instructions and unified output.",
        surface: "openai-responses",
        systemPrompt: "Answer as a terse operations assistant.",
        userPrompt: "Summarize why this proxy is useful in one sentence.",
        stream: false,
    },
    {
        id: "anthropic-messages",
        label: "Anthropic messages",
        description: "Smoke-checks the Anthropic-compatible router with a familiar payload shape.",
        surface: "anthropic-messages",
        systemPrompt: "You are concise.",
        userPrompt: "Say hello from the Anthropic-compatible surface.",
        stream: false,
    },
    {
        id: "gemini-stream",
        label: "Gemini stream",
        description: "Targets Gemini-compatible SSE and uses proper systemInstruction mapping.",
        surface: "gemini-generate",
        systemPrompt: "Be brief.",
        userPrompt: "Write a short stream smoke response.",
        stream: true,
    },
];
export function resolvePlaygroundModel(configuredModel) {
    return configuredModel?.trim() || FALLBACK_PLAYGROUND_MODEL;
}
export function buildPlaygroundPresets(configuredModel) {
    const model = resolvePlaygroundModel(configuredModel);
    return PLAYGROUND_PRESET_DEFINITIONS.map((preset) => ({
        ...preset,
        model,
    }));
}
export function createEmptyTokenUsage() {
    return {
        inputTokens: null,
        outputTokens: null,
        totalTokens: null,
    };
}
export function createIdleRunState() {
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
        tokenUsage: createEmptyTokenUsage(),
        assistantOutput: "",
        rawOutput: "",
        errorText: "",
    };
}
export function createPlaygroundPageState() {
    return {
        activeController: null,
        activeRunId: 0,
        runState: createIdleRunState(),
        streamEvents: [],
    };
}
export function getPlaygroundFields(form) {
    return form.elements;
}
