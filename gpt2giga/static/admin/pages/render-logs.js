export async function renderLogs(app, token) {
    if (!app.isCurrentRender(token)) {
        return;
    }
    app.setHeroActions(`
    <button class="button button--secondary" id="refresh-logs" type="button">Refresh tail</button>
    <button class="button" id="toggle-stream" type="button">Start live stream</button>
  `);
    app.setContent(`
    <article class="panel panel--span-3">
      <div class="stack">
        <h3>Tail options</h3>
        <label class="field">Lines <input id="log-lines" value="150" /></label>
      </div>
    </article>
    <article class="panel panel--span-9">
      <div class="stack">
        <h3>Live log output</h3>
        <pre class="code-block code-block--tall" id="log-output">Loading logs…</pre>
      </div>
    </article>
  `);
    const logOutput = app.pageContent.querySelector("#log-output");
    const logLines = app.pageContent.querySelector("#log-lines");
    const refreshButton = document.getElementById("refresh-logs");
    const streamButton = document.getElementById("toggle-stream");
    if (!logOutput || !logLines || !refreshButton || !streamButton) {
        return;
    }
    const controller = new AbortController();
    let streaming = false;
    app.registerCleanup(() => {
        controller.abort();
    });
    const refreshLogs = async () => {
        logOutput.textContent = await app.api.text(`/admin/api/logs?lines=${encodeURIComponent(logLines.value || "150")}`);
    };
    const startStream = async () => {
        streaming = true;
        const response = await app.api.raw("/admin/api/logs/stream", { signal: controller.signal });
        if (!response.body) {
            throw new Error("Log stream body is unavailable.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        while (streaming) {
            const { value, done } = await reader.read();
            if (done) {
                break;
            }
            logOutput.textContent += decoder.decode(value, { stream: true });
            logOutput.scrollTop = logOutput.scrollHeight;
        }
    };
    refreshButton.addEventListener("click", () => {
        void refreshLogs();
    });
    streamButton.addEventListener("click", async () => {
        if (streaming) {
            streaming = false;
            controller.abort();
            streamButton.textContent = "Start live stream";
            return;
        }
        streamButton.textContent = "Stop live stream";
        try {
            await startStream();
        }
        catch (error) {
            app.pushAlert(error instanceof Error ? error.message : String(error), "danger");
        }
        finally {
            streaming = false;
            streamButton.textContent = "Start live stream";
        }
    });
    await refreshLogs();
}
