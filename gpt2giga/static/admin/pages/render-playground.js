export async function renderPlayground(app, token) {
    if (!app.isCurrentRender(token)) {
        return;
    }
    app.setHeroActions(`<button class="button button--secondary" id="playground-reset" type="button">Reset output</button>`);
    app.setContent(`
    <article class="panel panel--span-4">
      <div class="stack">
        <h3>Request</h3>
        <form id="playground-form" class="stack">
          <label class="field">
            <span>Surface</span>
            <select name="surface">
              <option value="openai-chat">OpenAI chat/completions</option>
              <option value="openai-responses">OpenAI responses</option>
              <option value="anthropic-messages">Anthropic messages</option>
              <option value="gemini-generate">Gemini generateContent</option>
            </select>
          </label>
          <label class="field"><span>Model</span><input name="model" value="GigaChat" /></label>
          <label class="field"><span>System prompt</span><textarea name="system_prompt" placeholder="Optional system prompt"></textarea></label>
          <label class="field"><span>User prompt</span><textarea name="user_prompt">Привет! Ответь одной фразой.</textarea></label>
          <label class="field">
            <span>Stream</span>
            <select name="stream">
              <option value="false">off</option>
              <option value="true">on</option>
            </select>
          </label>
          <button class="button" type="submit">Send request</button>
        </form>
      </div>
    </article>
    <article class="panel panel--span-8">
      <div class="stack">
        <h3>Response</h3>
        <pre class="code-block code-block--tall" id="playground-output">No request yet.</pre>
      </div>
    </article>
  `);
    const form = app.pageContent.querySelector("#playground-form");
    const output = app.pageContent.querySelector("#playground-output");
    const resetButton = document.getElementById("playground-reset");
    if (!form || !output) {
        return;
    }
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const request = buildRequest(form);
        output.textContent = "Sending request…";
        const response = await app.api.raw(request.url, {
            method: "POST",
            json: request.body,
        }, true);
        output.textContent = await response.text();
    });
    resetButton?.addEventListener("click", () => {
        output.textContent = "No request yet.";
    });
}
function buildRequest(form) {
    const fields = form.elements;
    const surface = fields.surface.value;
    const model = fields.model.value.trim();
    const systemPrompt = fields.system_prompt.value.trim();
    const userPrompt = fields.user_prompt.value.trim();
    const stream = fields.stream.value === "true";
    if (surface === "openai-chat") {
        return {
            url: "/v1/chat/completions",
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
            url: "/v1/responses",
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
            url: "/v1/messages",
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
        url: `/v1beta/models/${encodeURIComponent(model)}:generateContent`,
        body: {
            contents: [
                {
                    role: "user",
                    parts: [{ text: systemPrompt ? `${systemPrompt}\n\n${userPrompt}` : userPrompt }],
                },
            ],
        },
    };
}
