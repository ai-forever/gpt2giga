import { AdminApiClient } from "./api.js";
import { PAGE_META, WORKFLOW_META, isConsolePathname, navEntryForPage, pageFromLocation, pathForPage, } from "./routes.js";
import { renderLoadingGrid } from "./templates.js";
import { describePersistenceStatus, escapeHtml, toErrorMessage, } from "./utils.js";
import { PAGE_RENDERERS } from "./pages/index.js";
const ADMIN_KEY_STORAGE = "gpt2giga.adminKey";
const GATEWAY_KEY_STORAGE = "gpt2giga.gatewayKey";
const ADMIN_KEY_COOKIE = "gpt2giga_admin_key";
const UNSAVED_CHANGES_MESSAGE = "You have unsaved setup or settings changes. Leave this page and discard them?";
export class AdminApp {
    pageContent = this.requireElement("page-content");
    alertsNode = this.requireElement("alerts");
    heroActions = this.requireElement("hero-actions");
    adminKeyInput = this.requireElement("admin-key-input");
    gatewayKeyInput = this.requireElement("gateway-key-input");
    modeChip = this.requireElement("mode-chip");
    backendChip = this.requireElement("backend-chip");
    runtimeStoreChip = this.requireElement("runtime-store-chip");
    persistedChip = this.requireElement("persisted-chip");
    versionChip = this.requireElement("version-chip");
    authDisclosure = document.getElementById("auth-disclosure");
    pageEyebrow = this.requireElement("page-eyebrow");
    pageTitle = this.requireElement("page-title");
    pageSubtitle = this.requireElement("page-subtitle");
    workflowChip = this.requireElement("workflow-chip");
    surfaceChip = this.requireElement("surface-chip");
    nav = this.requireElement("nav");
    saveAuthButton = this.requireElement("save-auth");
    compactNavMedia = window.matchMedia("(max-width: 720px)");
    apiClient;
    cleanups = [];
    dirtyForms = new Set();
    flashAlerts = [];
    renderToken = 0;
    shouldFocusPageHeading = false;
    lastKnownUrl = this.currentUrl();
    runtimePayload = null;
    constructor() {
        this.adminKeyInput.value = this.restoreSessionValue(ADMIN_KEY_STORAGE);
        this.gatewayKeyInput.value =
            this.restoreSessionValue(GATEWAY_KEY_STORAGE) || this.adminKeyInput.value;
        if (!this.adminKeyInput.value || !this.gatewayKeyInput.value) {
            this.authDisclosure?.setAttribute("open", "open");
        }
        this.apiClient = new AdminApiClient(() => this.adminKeyInput.value, () => this.gatewayKeyInput.value);
        this.hydrateKeysFromQuery();
        this.saveAuthButton.addEventListener("click", () => {
            this.persistAdminKey(this.adminKeyInput.value.trim());
            this.persistSessionValue(GATEWAY_KEY_STORAGE, this.gatewayKeyInput.value.trim());
            this.pushAlert("Saved API keys for this browser session.", "info");
        });
        this.installNavigation();
    }
    get api() {
        return this.apiClient;
    }
    get runtime() {
        return this.runtimePayload;
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
    setFormDirty(formKey, dirty) {
        if (dirty) {
            this.dirtyForms.add(formKey);
            return;
        }
        this.dirtyForms.delete(formKey);
    }
    setHero(page) {
        const meta = PAGE_META[page];
        const workflow = WORKFLOW_META[meta.workflow];
        const navPage = navEntryForPage(page);
        const navSurface = navPage === page ? meta.eyebrow : `${PAGE_META[navPage].eyebrow} detail`;
        this.pageEyebrow.textContent = meta.eyebrow;
        this.pageTitle.textContent = meta.title;
        this.pageSubtitle.textContent = meta.subtitle;
        this.workflowChip.textContent = workflow.label;
        this.surfaceChip.textContent = navSurface;
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
        this.navigateToLocation({
            hash: "",
            pathname: pathForPage(page),
            search: "",
        });
    }
    navigateToLocation(locationLike) {
        const nextUrl = `${locationLike.pathname}${locationLike.search}${locationLike.hash}`;
        const currentUrl = this.currentUrl();
        if (currentUrl !== nextUrl && !this.confirmDiscardUnsavedChanges()) {
            return;
        }
        if (currentUrl !== nextUrl) {
            window.history.pushState({}, "", nextUrl);
            this.lastKnownUrl = nextUrl;
        }
        this.shouldFocusPageHeading = true;
        void this.render(pageFromLocation({
            hash: locationLike.hash,
            pathname: locationLike.pathname,
            search: locationLike.search,
        }));
    }
    saveGatewayKey(value) {
        this.gatewayKeyInput.value = value;
        this.persistSessionValue(GATEWAY_KEY_STORAGE, value);
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
            <pre class="code-block">${escapeHtml(toErrorMessage(error))}</pre>
          </div>
        </article>
      `);
            this.pushAlert("The current page failed to load. Check your admin API key or recent logs.", "danger");
        }
        if (this.isCurrentRender(token) && this.shouldFocusPageHeading) {
            this.shouldFocusPageHeading = false;
            this.pageTitle.focus();
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
            this.runtimePayload = runtime;
            const persistence = describePersistenceStatus(setup);
            this.modeChip.textContent = String(runtime.mode ?? "n/a");
            this.backendChip.textContent = String(runtime.gigachat_api_mode ?? "n/a");
            this.runtimeStoreChip.textContent = String(runtime.runtime_store_backend ?? "n/a");
            this.persistedChip.textContent = persistence.chip;
            this.versionChip.textContent = String(runtime.app_version ?? "n/a");
            if (!setup.gigachat_ready) {
                this.pushAlert("Effective upstream GigaChat auth is missing. Playground calls will fail until credentials, access token, or user/password auth is configured.", "warn");
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
            this.runtimePayload = null;
            this.pushAlert(`Failed to load global admin status. ${toErrorMessage(error)}`, "danger");
            this.modeChip.textContent = "error";
            this.backendChip.textContent = "error";
            this.runtimeStoreChip.textContent = "error";
            this.persistedChip.textContent = "error";
            this.versionChip.textContent = "error";
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
        const storedGatewayKey = sessionStorage.getItem(GATEWAY_KEY_STORAGE)?.trim();
        if (!storedGatewayKey) {
            this.gatewayKeyInput.value = queryKey;
            this.persistSessionValue(GATEWAY_KEY_STORAGE, queryKey);
        }
        params.delete("x-api-key");
        const nextQuery = params.toString();
        const cleanUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}${window.location.hash}`;
        window.history.replaceState({}, "", cleanUrl);
        this.lastKnownUrl = cleanUrl;
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
            if (url.pathname === window.location.pathname &&
                url.search === window.location.search &&
                url.hash) {
                return;
            }
            event.preventDefault();
            this.navigateToLocation({
                hash: url.hash,
                pathname: url.pathname,
                search: url.search,
            });
        });
        window.addEventListener("beforeunload", (event) => {
            if (!this.hasUnsavedChanges()) {
                return;
            }
            event.preventDefault();
            event.returnValue = "";
        });
        window.addEventListener("popstate", () => {
            const nextUrl = this.currentUrl();
            const previousUrl = this.lastKnownUrl;
            if (nextUrl !== previousUrl && !this.confirmDiscardUnsavedChanges()) {
                window.history.pushState({}, "", previousUrl);
                return;
            }
            this.lastKnownUrl = nextUrl;
            this.shouldFocusPageHeading = true;
            void this.render();
        });
        const syncCompactNav = () => {
            this.syncNavSections();
        };
        this.compactNavMedia.addEventListener("change", syncCompactNav);
    }
    setNav(page) {
        const navPage = navEntryForPage(page);
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
        this.syncNavSections();
    }
    syncNavSections() {
        const compactNav = this.compactNavMedia.matches;
        this.nav.querySelectorAll("[data-nav-section]").forEach((section) => {
            const links = Array.from(section.querySelectorAll("a[href]"));
            const activeLink = links.find((link) => link.classList.contains("active")) ?? null;
            const summaryMeta = section.querySelector("[data-nav-section-meta]");
            section.toggleAttribute("data-active", activeLink !== null);
            section.open = compactNav ? false : true;
            if (!summaryMeta) {
                return;
            }
            if (activeLink) {
                const activeLabel = activeLink.querySelector("strong")?.textContent?.trim() ?? "Current surface";
                summaryMeta.textContent = `${activeLabel} active`;
                return;
            }
            summaryMeta.textContent = `${links.length} surfaces`;
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
        this.persistSessionValue(ADMIN_KEY_STORAGE, value);
        const secure = window.location.protocol === "https:" ? "; Secure" : "";
        if (!value) {
            document.cookie = `${ADMIN_KEY_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax${secure}`;
            return;
        }
        document.cookie = `${ADMIN_KEY_COOKIE}=${encodeURIComponent(value)}; Path=/; SameSite=Lax${secure}`;
    }
    restoreSessionValue(key) {
        const sessionValue = sessionStorage.getItem(key)?.trim();
        if (sessionValue) {
            return sessionValue;
        }
        const legacyValue = localStorage.getItem(key)?.trim();
        if (!legacyValue) {
            return "";
        }
        this.persistSessionValue(key, legacyValue);
        return legacyValue;
    }
    persistSessionValue(key, value) {
        if (value) {
            sessionStorage.setItem(key, value);
        }
        else {
            sessionStorage.removeItem(key);
        }
        localStorage.removeItem(key);
    }
    hasUnsavedChanges() {
        return this.dirtyForms.size > 0;
    }
    confirmDiscardUnsavedChanges() {
        return !this.hasUnsavedChanges() || window.confirm(UNSAVED_CHANGES_MESSAGE);
    }
    currentUrl() {
        return `${window.location.pathname}${window.location.search}${window.location.hash}`;
    }
}
