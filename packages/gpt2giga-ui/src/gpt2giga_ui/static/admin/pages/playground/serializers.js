import { asRecord } from "../../utils.js";
import { createEmptyTokenUsage, DEFAULT_OUTPUT, getPlaygroundFields, resolvePlaygroundModel, } from "./state.js";
export function applyPreset(form, preset) {
    const fields = getPlaygroundFields(form);
    fields.surface.value = preset.surface;
    fields.model.value = preset.model;
    fields.system_prompt.value = preset.systemPrompt;
    fields.user_prompt.value = preset.userPrompt;
    fields.stream.value = String(preset.stream);
}
export function buildRequest(form, configuredModel) {
    const fields = getPlaygroundFields(form);
    return buildRequestFromState({
        surface: fields.surface.value,
        model: fields.model.value.trim() || resolvePlaygroundModel(configuredModel),
        systemPrompt: fields.system_prompt.value.trim(),
        userPrompt: fields.user_prompt.value.trim(),
        stream: fields.stream.value === "true",
    });
}
export function buildRequestFromPreset(preset) {
    return buildRequestFromState({
        surface: preset.surface,
        model: preset.model,
        systemPrompt: preset.systemPrompt,
        userPrompt: preset.userPrompt,
        stream: preset.stream,
    });
}
export function applyPlainResponse(rawText, request, runState) {
    const contentType = runState.contentType.toLowerCase();
    const parsedJson = tryParseJson(rawText);
    const displayText = parsedJson !== null
        ? JSON.stringify(parsedJson, null, 2)
        : contentType.startsWith("text/")
            ? rawText
            : rawText || "(empty response body)";
    runState.rawOutput = displayText || "(empty response body)";
    runState.assistantOutput =
        (parsedJson !== null ? extractAssistantText(parsedJson, request.surface) : rawText).trim() ||
            "";
    runState.tokenUsage = mergeTokenUsage(runState.tokenUsage, parsedJson !== null ? extractTokenUsage(parsedJson) : null);
}
export function buildGatewayHeaders(surface, gatewayKey, stream) {
    const headers = new Headers({
        "Content-Type": "application/json",
    });
    if (stream) {
        headers.set("Accept", "text/event-stream");
    }
    if (!gatewayKey) {
        return headers;
    }
    headers.set("Authorization", `Bearer ${gatewayKey}`);
    if (surface === "gemini-generate") {
        headers.set("x-goog-api-key", gatewayKey);
    }
    return headers;
}
export function extractTokenUsage(payload) {
    const record = asRecord(payload);
    return (extractUsageFromContainer(record) ??
        extractUsageFromContainer(asRecord(record.response)) ??
        extractUsageFromContainer(asRecord(record.message)));
}
export function mergeTokenUsage(current, next) {
    if (next === null) {
        return current;
    }
    const inputTokens = next.inputTokens ?? current.inputTokens;
    const outputTokens = next.outputTokens ?? current.outputTokens;
    const totalTokens = next.totalTokens ??
        current.totalTokens ??
        (inputTokens !== null && outputTokens !== null ? inputTokens + outputTokens : null);
    return {
        inputTokens,
        outputTokens,
        totalTokens,
    };
}
export function tryParseJson(value) {
    if (!value.trim()) {
        return null;
    }
    try {
        return JSON.parse(value);
    }
    catch {
        return null;
    }
}
export function extractAssistantText(payload, surface) {
    const record = asRecord(payload);
    if (typeof record.output_text === "string") {
        return String(record.output_text);
    }
    if (Array.isArray(record.output_text)) {
        return record.output_text.map(String).join("");
    }
    if (Array.isArray(record.choices)) {
        const parts = record.choices.flatMap((choice) => {
            const choiceRecord = asRecord(choice);
            return [
                extractMessageContent(choiceRecord.message),
                extractMessageContent(choiceRecord.delta),
                extractTextValue(choiceRecord.text),
            ].filter(Boolean);
        });
        if (parts.length) {
            return parts.join("");
        }
    }
    if (Array.isArray(record.content)) {
        const text = record.content
            .flatMap((item) => {
            const itemRecord = asRecord(item);
            if (typeof itemRecord.text === "string") {
                return [itemRecord.text];
            }
            if (Array.isArray(itemRecord.content)) {
                return itemRecord.content.map((part) => extractTextValue(part)).filter(Boolean);
            }
            return [];
        })
            .join("");
        if (text) {
            return text;
        }
    }
    if (record.delta) {
        const deltaText = extractMessageContent(record.delta) || extractTextValue(record.delta);
        if (deltaText) {
            return deltaText;
        }
    }
    if (Array.isArray(record.candidates)) {
        const candidateText = record.candidates
            .flatMap((candidate) => {
            const content = asRecord(asRecord(candidate).content);
            return Array.isArray(content.parts)
                ? content.parts.map((part) => extractTextValue(part)).filter(Boolean)
                : [];
        })
            .join("");
        if (candidateText) {
            return candidateText;
        }
    }
    if (surface === "openai-responses" && Array.isArray(record.output)) {
        const outputText = record.output
            .flatMap((item) => {
            const itemRecord = asRecord(item);
            if (Array.isArray(itemRecord.content)) {
                return itemRecord.content.map((part) => extractTextValue(part)).filter(Boolean);
            }
            return [];
        })
            .join("");
        if (outputText) {
            return outputText;
        }
    }
    return "";
}
export function mergeAssistantOutput(current, next, eventType, payload, surface) {
    if (!next) {
        return current;
    }
    const candidate = next;
    const lowerType = eventType.toLowerCase();
    const payloadRecord = asRecord(payload);
    const choiceList = Array.isArray(payloadRecord.choices) ? payloadRecord.choices : [];
    const isDeltaEvent = surface === "gemini-generate" ||
        lowerType.includes("delta") ||
        lowerType.includes("chunk") ||
        Boolean(payloadRecord.delta) ||
        Boolean(asRecord(choiceList[0]).delta);
    if (!current) {
        return candidate;
    }
    if (candidate.startsWith(current)) {
        return candidate;
    }
    if (!isDeltaEvent) {
        return candidate.length >= current.length ? candidate : current;
    }
    return appendTextDelta(current, candidate);
}
export function formatSseTranscript(events) {
    if (!events.length) {
        return DEFAULT_OUTPUT;
    }
    return events
        .map((event, index) => {
        if (event.data === "[DONE]") {
            return `#${index + 1} ${event.type}\n[DONE]`;
        }
        const parsed = tryParseJson(event.data);
        const body = parsed === null ? event.data : JSON.stringify(parsed, null, 2);
        return `#${index + 1} ${event.type}\n${body}`;
    })
        .join("\n\n");
}
export function isAbortError(error) {
    return error instanceof DOMException
        ? error.name === "AbortError"
        : error instanceof Error && error.name === "AbortError";
}
function buildRequestFromState({ surface, model, systemPrompt, userPrompt, stream, }) {
    if (surface === "openai-chat") {
        return {
            surface,
            label: "OpenAI chat/completions",
            url: "/v1/chat/completions",
            stream,
            authLabel: "Authorization: Bearer",
            body: {
                model,
                stream,
                messages: [
                    ...(systemPrompt ? [{ role: "system", content: systemPrompt }] : []),
                    { role: "user", content: userPrompt },
                ],
            },
        };
    }
    if (surface === "openai-responses") {
        return {
            surface,
            label: "OpenAI responses",
            url: "/v1/responses",
            stream,
            authLabel: "Authorization: Bearer",
            body: {
                model,
                stream,
                instructions: systemPrompt || undefined,
                input: userPrompt,
            },
        };
    }
    if (surface === "anthropic-messages") {
        return {
            surface,
            label: "Anthropic messages",
            url: "/v1/messages",
            stream,
            authLabel: "Authorization: Bearer",
            body: {
                model,
                stream,
                max_tokens: 256,
                system: systemPrompt || undefined,
                messages: [{ role: "user", content: userPrompt }],
            },
        };
    }
    return {
        surface,
        label: "Gemini generateContent",
        url: stream
            ? `/v1beta/models/${encodeURIComponent(model)}:streamGenerateContent?alt=sse`
            : `/v1beta/models/${encodeURIComponent(model)}:generateContent`,
        stream,
        authLabel: "Authorization: Bearer + x-goog-api-key",
        body: {
            ...(systemPrompt
                ? {
                    systemInstruction: {
                        parts: [{ text: systemPrompt }],
                    },
                }
                : {}),
            contents: [
                {
                    role: "user",
                    parts: [{ text: userPrompt }],
                },
            ],
        },
    };
}
function extractMessageContent(value) {
    const record = asRecord(value);
    if (typeof record.content === "string") {
        return record.content;
    }
    if (Array.isArray(record.content)) {
        return record.content.map((part) => extractTextValue(part)).filter(Boolean).join("");
    }
    return "";
}
function extractTextValue(value) {
    if (typeof value === "string") {
        return value;
    }
    const record = asRecord(value);
    if (typeof record.text === "string") {
        return record.text;
    }
    if (typeof record.value === "string") {
        return record.value;
    }
    if (typeof record.partial_json === "string") {
        return record.partial_json;
    }
    return "";
}
function appendTextDelta(current, next) {
    if (!next) {
        return current;
    }
    if (current.endsWith(next)) {
        return current;
    }
    return current + next;
}
function extractUsageFromContainer(container) {
    const usage = asRecord(container.usage);
    const usageMetadata = asRecord(container.usageMetadata);
    return normalizeTokenUsage({
        inputTokens: usage.input_tokens ??
            usage.prompt_tokens ??
            container.input_tokens ??
            container.prompt_tokens ??
            usageMetadata.promptTokenCount,
        outputTokens: usage.output_tokens ??
            usage.completion_tokens ??
            container.output_tokens ??
            container.completion_tokens ??
            usageMetadata.candidatesTokenCount,
        totalTokens: usage.total_tokens ?? container.total_tokens ?? usageMetadata.totalTokenCount,
    });
}
function normalizeTokenUsage(candidate) {
    const inputTokens = readTokenCount(candidate.inputTokens);
    const outputTokens = readTokenCount(candidate.outputTokens);
    const totalTokens = readTokenCount(candidate.totalTokens);
    if (inputTokens === null && outputTokens === null && totalTokens === null) {
        return null;
    }
    return mergeTokenUsage(createEmptyTokenUsage(), {
        inputTokens,
        outputTokens,
        totalTokens,
    });
}
function readTokenCount(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric >= 0 ? numeric : null;
}
