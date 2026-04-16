import { bindLogsPage } from "./logs/bindings.js";
import { loadLogsPageData } from "./logs/api.js";
import { readLogsFilters } from "./logs/serializers.js";
import { renderLogsHeroActions, renderLogsPage, resolveLogsElements } from "./logs/view.js";
export async function renderLogs(app, token) {
    const filters = readLogsFilters();
    const data = await loadLogsPageData(app, filters);
    if (!app.isCurrentRender(token)) {
        return;
    }
    app.setHeroActions(renderLogsHeroActions(filters));
    app.setContent(renderLogsPage(data, filters));
    const elements = resolveLogsElements(app.pageContent);
    if (!elements) {
        return;
    }
    bindLogsPage({
        app,
        data,
        elements,
        filters,
        token,
    });
}
