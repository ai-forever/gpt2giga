import { AdminApiClient } from "./api.js";
import { PAGE_META, WORKFLOW_META, isConsolePathname, navEntryForPage, pageFromLocation, pathForPage, } from "./routes.js";
import { renderLoadingGrid } from "./templates.js";
import { toErrorMessage } from "./utils.js";
import { PAGE_RENDERERS } from "./pages/index.js";
const ADMIN_KEY_STORAGE = "gpt2giga.adminKey";
const GATEWAY_KEY_STORAGE = "gpt2giga.gatewayKey";
const ADMIN_KEY_COOKIE = "gpt2giga_admin_key";
const ADMIN_KEY_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;
export class AdminApp {
    pageContent = this.requireElement("page-content");
    alertsNode = this.requireElement("alerts");
    heroActions = this.requireElement("hero-actions");
    adminKeyInput = this.requireElement("admin-key-input");
    gatewayKeyInput = this.requireElement("gateway-key-input");
    modeChip = this.requireElement("mode-chip");
    backendChip = this.requireElement("backend-chip");
    persistedChip = this.requireElement("persisted-chip");
    authDisclosure = document.getElementById("auth-disclosure");
    pageEyebrow = this.requireElement("page-eyebrow");
    pageTitle = this.requireElement("page-title");
    pageSubtitle = this.requireElement("page-subtitle");
    workflowChip = this.requireElement("workflow-chip");
    surfaceChip = this.requireElement("surface-chip");
    pageContext = this.requireElement("page-context");
    nav = this.requireElement("nav");
    saveAuthButton = this.requireElement("save-auth");
    apiClient;
    cleanups = [];
    flashAlerts = [];
    renderToken = 0;
    constructor() {
        this.adminKeyInput.value = localStorage.getItem(ADMIN_KEY_STORAGE) || "";
        this.gatewayKeyInput.value =
            localStorage.getItem(GATEWAY_KEY_STORAGE) || this.adminKeyInput.value;
        if (!this.adminKeyInput.value || !this.gatewayKeyInput.value) {
            this.authDisclosure?.setAttribute("open", "open");
        }
        this.apiClient = new AdminApiClient(() => this.adminKeyInput.value, () => this.gatewayKeyInput.value);
        this.hydrateKeysFromQuery();
        this.saveAuthButton.addEventListener("click", () => {
            this.persistAdminKey(this.adminKeyInput.value.trim());
            localStorage.setItem(GATEWAY_KEY_STORAGE, this.gatewayKeyInput.value.trim());
            this.pushAlert("Saved API keys in browser local storage.", "info");
        });
        this.installNavigation();
    }
    get api() {
        return this.apiClient;
    }
    currentPage() {
        return pageFromLocation(window.location);
    }
    isCurrentRender(token) {
        return token === this.renderToken;
    }
    registerCleanup(cleanup) {
        this.cleanups.push(cleanup);
    }
    setHero(page) {
        const meta = PAGE_META[page];
        const workflow = WORKFLOW_META[meta.workflow];
        const navPage = navEntryForPage(page);
        const navSurface = navPage === page ? meta.eyebrow : `${PAGE_META[navPage].eyebrow} detail`;
        this.pageEyebrow.textContent = `${workflow.label} · ${meta.eyebrow}`;
        this.pageTitle.textContent = meta.title;
        this.pageSubtitle.textContent = meta.subtitle;
        this.workflowChip.textContent = `${workflow.label} workflow`;
        this.surfaceChip.textContent = navSurface;
        this.pageContext.textContent = meta.navDescription;
    }
    setHeroActions(html) {
        this.heroActions.innerHTML = html;
    }
    setContent(html) {
        this.pageContent.innerHTML = html;
    }
    pushAlert(message, tone = "info") {
        const node = document.createElement("div");
        node.className =
            tone === "danger"
                ? "banner banner--danger"
                : tone === "warn"
                    ? "banner banner--warn"
                    : "banner";
        node.textContent = message;
        this.alertsNode.prepend(node);
    }
    queueAlert(message, tone = "info") {
        this.flashAlerts.push({ message, tone });
    }
    navigate(page) {
        const nextPath = pathForPage(page);
        const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        if (currentUrl !== nextPath) {
            window.history.pushState({}, "", nextPath);
        }
        void this.render(page);
    }
    saveGatewayKey(value) {
        this.gatewayKeyInput.value = value;
        localStorage.setItem(GATEWAY_KEY_STORAGE, value);
    }
    saveAdminKey(value) {
        this.adminKeyInput.value = value;
        this.persistAdminKey(value);
    }
    async render(page = this.currentPage()) {
        this.renderToken += 1;
        const token = this.renderToken;
        await this.runCleanup();
        this.alertsNode.innerHTML = "";
        this.setHero(page);
        this.setNav(page);
        this.setHeroActions("");
        this.setContent(renderLoadingGrid());
        this.flushFlashAlerts();
        await this.loadGlobalStatus();
        if (!this.isCurrentRender(token)) {
            return;
        }
        try {
            await PAGE_RENDERERS[page](this, token);
        }
        catch (error) {
            if (!this.isCurrentRender(token)) {
                return;
            }
            this.setContent(`
        <article class="panel panel--span-12">
          <div class="stack">
            <h3>Request failed</h3>
            <pre class="code-block">${toErrorMessage(error)}</pre>
          </div>
        </article>
      `);
            this.pushAlert("The current page failed to load. Check your admin API key or recent logs.", "danger");
        }
    }
    async runCleanup() {
        const pending = this.cleanups;
        this.cleanups = [];
        await Promise.all(pending.map(async (cleanup) => cleanup()));
    }
    flushFlashAlerts() {
        const queued = this.flashAlerts;
        this.flashAlerts = [];
        queued.forEach((item) => this.pushAlert(item.message, item.tone));
    }
    async loadGlobalStatus() {
        try {
            const [runtime, setup] = await Promise.all([
                this.api.json("/admin/api/runtime"),
                this.api.json("/admin/api/setup"),
            ]);
            this.modeChip.textContent = String(runtime.mode ?? "n/a");
            this.backendChip.textContent = String(runtime.gigachat_api_mode ?? "n/a");
            this.persistedChip.textContent = setup.persisted ? "persisted" : "defaults";
            if (!setup.gigachat_ready) {
                this.pushAlert("GigaChat credentials are not configured yet. Playground calls will fail until the GigaChat section is filled.", "warn");
            }
            if (!setup.security_ready) {
                this.pushAlert("Gateway auth bootstrap is incomplete. Create a global or scoped API key before exposing the proxy.", "warn");
            }
            const bootstrap = setup.bootstrap;
            if (bootstrap?.required) {
                this.pushAlert("PROD bootstrap mode is active. Until setup is complete, admin access is limited to localhost or the bootstrap token.", "warn");
            }
        }
        catch (error) {
            this.pushAlert(`Failed to load global admin status. ${toErrorMessage(error)}`, "danger");
            this.modeChip.textContent = "error";
            this.backendChip.textContent = "error";
            this.persistedChip.textContent = "error";
        }
    }
    hydrateKeysFromQuery() {
        const params = new URLSearchParams(window.location.search);
        const queryKey = params.get("x-api-key")?.trim();
        if (!queryKey) {
            return;
        }
        this.adminKeyInput.value = queryKey;
        this.persistAdminKey(queryKey);
        const storedGatewayKey = localStorage.getItem(GATEWAY_KEY_STORAGE)?.trim();
        if (!storedGatewayKey) {
            this.gatewayKeyInput.value = queryKey;
            localStorage.setItem(GATEWAY_KEY_STORAGE, queryKey);
        }
        params.delete("x-api-key");
        const nextQuery = params.toString();
        const cleanUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}${window.location.hash}`;
        window.history.replaceState({}, "", cleanUrl);
    }
    installNavigation() {
        document.addEventListener("click", (event) => {
            if (event.defaultPrevented || event.button !== 0) {
                return;
            }
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                return;
            }
            const target = event.target;
            if (!(target instanceof Element)) {
                return;
            }
            const anchor = target.closest("a[href]");
            if (!anchor || (anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) {
                return;
            }
            const url = new URL(anchor.href, window.location.origin);
            if (url.origin !== window.location.origin || !isConsolePathname(url.pathname)) {
                return;
            }
            event.preventDefault();
            const nextPage = pageFromLocation({
                hash: url.hash,
                pathname: url.pathname,
                search: url.search,
            });
            this.navigate(nextPage);
        });
        window.addEventListener("popstate", () => {
            void this.render();
        });
    }
    setNav(page) {
        const navPage = navEntryForPage(page);
        const workflow = PAGE_META[page].workflow;
        this.nav.querySelectorAll(".nav-group").forEach((group) => {
            group.classList.toggle("nav-group--active", group.dataset.workflow === workflow);
        });
        this.nav.querySelectorAll("a[href]").forEach((link) => {
            const href = link.getAttribute("href");
            const matchesOverview = navPage === "overview" && (href === "/admin" || href === "/admin/overview");
            const active = matchesOverview || href === pathForPage(navPage);
            link.classList.toggle("active", active);
            if (active) {
                link.setAttribute("aria-current", "page");
            }
            else {
                link.removeAttribute("aria-current");
            }
        });
    }
    requireElement(id) {
        const node = document.getElementById(id);
        if (!node) {
            throw new Error(`Missing required element #${id}`);
        }
        return node;
    }
    persistAdminKey(value) {
        localStorage.setItem(ADMIN_KEY_STORAGE, value);
        const secure = window.location.protocol === "https:" ? "; Secure" : "";
        document.cookie = `${ADMIN_KEY_COOKIE}=${encodeURIComponent(value)}; Path=/; Max-Age=${ADMIN_KEY_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax${secure}`;
    }
}
