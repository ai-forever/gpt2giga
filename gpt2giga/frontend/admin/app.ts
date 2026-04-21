import { AdminApiClient } from "./api.js";
import {
  PAGE_META,
  WORKFLOW_META,
  isConsolePathname,
  navEntryForPage,
  pageFromLocation,
  pathForPage,
} from "./routes.js";
import { renderLoadingGrid } from "./templates.js";
import type {
  AlertMessage,
  AlertTone,
  PageId,
  RuntimePayload,
  SetupPayload,
} from "./types.js";
import {
  describePersistenceStatus,
  escapeHtml,
  toErrorMessage,
} from "./utils.js";
import { PAGE_RENDERERS } from "./pages/index.js";

const ADMIN_KEY_STORAGE = "gpt2giga.adminKey";
const GATEWAY_KEY_STORAGE = "gpt2giga.gatewayKey";
const ADMIN_KEY_COOKIE = "gpt2giga_admin_key";
const UNSAVED_CHANGES_MESSAGE =
  "You have unsaved setup or settings changes. Leave this page and discard them?";

type CleanupFn = () => void | Promise<void>;

export class AdminApp {
  readonly pageContent = this.requireElement<HTMLElement>("page-content");
  readonly alertsNode = this.requireElement<HTMLElement>("alerts");
  readonly heroActions = this.requireElement<HTMLElement>("hero-actions");
  readonly adminKeyInput = this.requireElement<HTMLInputElement>("admin-key-input");
  readonly gatewayKeyInput = this.requireElement<HTMLInputElement>("gateway-key-input");
  private readonly modeChip = this.requireElement<HTMLElement>("mode-chip");
  private readonly backendChip = this.requireElement<HTMLElement>("backend-chip");
  private readonly persistedChip = this.requireElement<HTMLElement>("persisted-chip");
  private readonly versionChip = this.requireElement<HTMLElement>("version-chip");
  private readonly authDisclosure = document.getElementById("auth-disclosure") as HTMLDetailsElement | null;
  private readonly pageEyebrow = this.requireElement<HTMLElement>("page-eyebrow");
  private readonly pageTitle = this.requireElement<HTMLElement>("page-title");
  private readonly pageSubtitle = this.requireElement<HTMLElement>("page-subtitle");
  private readonly workflowChip = this.requireElement<HTMLElement>("workflow-chip");
  private readonly surfaceChip = this.requireElement<HTMLElement>("surface-chip");
  private readonly nav = this.requireElement<HTMLElement>("nav");
  private readonly saveAuthButton = this.requireElement<HTMLButtonElement>("save-auth");
  private readonly compactNavMedia = window.matchMedia("(max-width: 720px)");

  private readonly apiClient: AdminApiClient;
  private cleanups: CleanupFn[] = [];
  private readonly dirtyForms = new Set<string>();
  private flashAlerts: AlertMessage[] = [];
  private renderToken = 0;
  private shouldFocusPageHeading = false;
  private lastKnownUrl = this.currentUrl();

  constructor() {
    this.adminKeyInput.value = this.restoreSessionValue(ADMIN_KEY_STORAGE);
    this.gatewayKeyInput.value =
      this.restoreSessionValue(GATEWAY_KEY_STORAGE) || this.adminKeyInput.value;
    if (!this.adminKeyInput.value || !this.gatewayKeyInput.value) {
      this.authDisclosure?.setAttribute("open", "open");
    }
    this.apiClient = new AdminApiClient(
      () => this.adminKeyInput.value,
      () => this.gatewayKeyInput.value,
    );

    this.hydrateKeysFromQuery();
    this.saveAuthButton.addEventListener("click", () => {
      this.persistAdminKey(this.adminKeyInput.value.trim());
      this.persistSessionValue(GATEWAY_KEY_STORAGE, this.gatewayKeyInput.value.trim());
      this.pushAlert("Saved API keys for this browser session.", "info");
    });
    this.installNavigation();
  }

  get api(): AdminApiClient {
    return this.apiClient;
  }

  currentPage(): PageId {
    return pageFromLocation(window.location);
  }

  isCurrentRender(token: number): boolean {
    return token === this.renderToken;
  }

  registerCleanup(cleanup: CleanupFn): void {
    this.cleanups.push(cleanup);
  }

  setFormDirty(formKey: string, dirty: boolean): void {
    if (dirty) {
      this.dirtyForms.add(formKey);
      return;
    }
    this.dirtyForms.delete(formKey);
  }

  setHero(page: PageId): void {
    const meta = PAGE_META[page];
    const workflow = WORKFLOW_META[meta.workflow];
    const navPage = navEntryForPage(page);
    const navSurface =
      navPage === page ? meta.eyebrow : `${PAGE_META[navPage].eyebrow} detail`;

    this.pageEyebrow.textContent = meta.eyebrow;
    this.pageTitle.textContent = meta.title;
    this.pageSubtitle.textContent = meta.subtitle;
    this.workflowChip.textContent = workflow.label;
    this.surfaceChip.textContent = navSurface;
  }

  setHeroActions(html: string): void {
    this.heroActions.innerHTML = html;
  }

  setContent(html: string): void {
    this.pageContent.innerHTML = html;
  }

  pushAlert(message: string, tone: AlertTone = "info"): void {
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

  queueAlert(message: string, tone: AlertTone = "info"): void {
    this.flashAlerts.push({ message, tone });
  }

  navigate(page: PageId): void {
    this.navigateToLocation({
      hash: "",
      pathname: pathForPage(page),
      search: "",
    });
  }

  navigateToLocation(locationLike: Pick<Location, "hash" | "pathname" | "search">): void {
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
    void this.render(
      pageFromLocation({
        hash: locationLike.hash,
        pathname: locationLike.pathname,
        search: locationLike.search,
      } as Location),
    );
  }

  saveGatewayKey(value: string): void {
    this.gatewayKeyInput.value = value;
    this.persistSessionValue(GATEWAY_KEY_STORAGE, value);
  }

  saveAdminKey(value: string): void {
    this.adminKeyInput.value = value;
    this.persistAdminKey(value);
  }

  async render(page = this.currentPage()): Promise<void> {
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
    } catch (error) {
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
      this.pushAlert(
        "The current page failed to load. Check your admin API key or recent logs.",
        "danger",
      );
    }

    if (this.isCurrentRender(token) && this.shouldFocusPageHeading) {
      this.shouldFocusPageHeading = false;
      this.pageTitle.focus();
    }
  }

  private async runCleanup(): Promise<void> {
    const pending = this.cleanups;
    this.cleanups = [];
    await Promise.all(pending.map(async (cleanup) => cleanup()));
  }

  private flushFlashAlerts(): void {
    const queued = this.flashAlerts;
    this.flashAlerts = [];
    queued.forEach((item) => this.pushAlert(item.message, item.tone));
  }

  private async loadGlobalStatus(): Promise<void> {
    try {
      const [runtime, setup] = await Promise.all([
        this.api.json<RuntimePayload>("/admin/api/runtime"),
        this.api.json<SetupPayload>("/admin/api/setup"),
      ]);

      const persistence = describePersistenceStatus(setup);
      this.modeChip.textContent = String(runtime.mode ?? "n/a");
      this.backendChip.textContent = String(runtime.gigachat_api_mode ?? "n/a");
      this.persistedChip.textContent = persistence.chip;
      this.versionChip.textContent = String(runtime.app_version ?? "n/a");

      if (!setup.gigachat_ready) {
        this.pushAlert(
          "Effective upstream GigaChat auth is missing. Playground calls will fail until credentials, access token, or user/password auth is configured.",
          "warn",
        );
      }
      if (!setup.security_ready) {
        this.pushAlert(
          "Gateway auth bootstrap is incomplete. Create a global or scoped API key before exposing the proxy.",
          "warn",
        );
      }
      const bootstrap = setup.bootstrap as Record<string, unknown> | undefined;
      if (bootstrap?.required) {
        this.pushAlert(
          "PROD bootstrap mode is active. Until setup is complete, admin access is limited to localhost or the bootstrap token.",
          "warn",
        );
      }
    } catch (error) {
      this.pushAlert(`Failed to load global admin status. ${toErrorMessage(error)}`, "danger");
      this.modeChip.textContent = "error";
      this.backendChip.textContent = "error";
      this.persistedChip.textContent = "error";
      this.versionChip.textContent = "error";
    }
  }

  private hydrateKeysFromQuery(): void {
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

  private installNavigation(): void {
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

      const anchor = target.closest<HTMLAnchorElement>("a[href]");
      if (!anchor || (anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) {
        return;
      }

      const url = new URL(anchor.href, window.location.origin);
      if (url.origin !== window.location.origin || !isConsolePathname(url.pathname)) {
        return;
      }
      if (
        url.pathname === window.location.pathname &&
        url.search === window.location.search &&
        url.hash
      ) {
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

    const syncCompactNav = (): void => {
      this.syncNavSections();
    };
    this.compactNavMedia.addEventListener("change", syncCompactNav);
  }

  private setNav(page: PageId): void {
    const navPage = navEntryForPage(page);

    this.nav.querySelectorAll("a[href]").forEach((link) => {
      const href = link.getAttribute("href");
      const matchesOverview =
        navPage === "overview" && (href === "/admin" || href === "/admin/overview");
      const active = matchesOverview || href === pathForPage(navPage);
      link.classList.toggle("active", active);
      if (active) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });

    this.syncNavSections();
  }

  private syncNavSections(): void {
    const compactNav = this.compactNavMedia.matches;

    this.nav.querySelectorAll<HTMLDetailsElement>("[data-nav-section]").forEach((section) => {
      const links = Array.from(section.querySelectorAll<HTMLAnchorElement>("a[href]"));
      const activeLink =
        links.find((link) => link.classList.contains("active")) ?? null;
      const summaryMeta = section.querySelector<HTMLElement>("[data-nav-section-meta]");

      section.toggleAttribute("data-active", activeLink !== null);
      section.open = compactNav ? false : true;

      if (!summaryMeta) {
        return;
      }

      if (activeLink) {
        const activeLabel =
          activeLink.querySelector("strong")?.textContent?.trim() ?? "Current surface";
        summaryMeta.textContent = `${activeLabel} active`;
        return;
      }

      summaryMeta.textContent = `${links.length} surfaces`;
    });
  }

  private requireElement<T extends HTMLElement>(id: string): T {
    const node = document.getElementById(id);
    if (!node) {
      throw new Error(`Missing required element #${id}`);
    }
    return node as T;
  }

  private persistAdminKey(value: string): void {
    this.persistSessionValue(ADMIN_KEY_STORAGE, value);
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    if (!value) {
      document.cookie = `${ADMIN_KEY_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax${secure}`;
      return;
    }
    document.cookie = `${ADMIN_KEY_COOKIE}=${encodeURIComponent(value)}; Path=/; SameSite=Lax${secure}`;
  }

  private restoreSessionValue(key: string): string {
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

  private persistSessionValue(key: string, value: string): void {
    if (value) {
      sessionStorage.setItem(key, value);
    } else {
      sessionStorage.removeItem(key);
    }
    localStorage.removeItem(key);
  }

  private hasUnsavedChanges(): boolean {
    return this.dirtyForms.size > 0;
  }

  private confirmDiscardUnsavedChanges(): boolean {
    return !this.hasUnsavedChanges() || window.confirm(UNSAVED_CHANGES_MESSAGE);
  }

  private currentUrl(): string {
    return `${window.location.pathname}${window.location.search}${window.location.hash}`;
  }
}
