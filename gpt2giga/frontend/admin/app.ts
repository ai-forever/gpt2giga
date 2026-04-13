import { AdminApiClient } from "./api";
import { PAGE_META, isConsolePathname, pageFromLocation, pathForPage } from "./routes";
import { renderLoadingGrid } from "./templates";
import type {
  AlertMessage,
  AlertTone,
  PageId,
  RuntimePayload,
  SetupPayload,
} from "./types";
import { toErrorMessage } from "./utils";
import { PAGE_RENDERERS } from "./pages/index";

const ADMIN_KEY_STORAGE = "gpt2giga.adminKey";
const GATEWAY_KEY_STORAGE = "gpt2giga.gatewayKey";

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
  private readonly pageEyebrow = this.requireElement<HTMLElement>("page-eyebrow");
  private readonly pageTitle = this.requireElement<HTMLElement>("page-title");
  private readonly pageSubtitle = this.requireElement<HTMLElement>("page-subtitle");
  private readonly nav = this.requireElement<HTMLElement>("nav");
  private readonly saveAuthButton = this.requireElement<HTMLButtonElement>("save-auth");

  private readonly apiClient: AdminApiClient;
  private cleanups: CleanupFn[] = [];
  private flashAlerts: AlertMessage[] = [];
  private renderToken = 0;

  constructor() {
    this.adminKeyInput.value = localStorage.getItem(ADMIN_KEY_STORAGE) || "";
    this.gatewayKeyInput.value =
      localStorage.getItem(GATEWAY_KEY_STORAGE) || this.adminKeyInput.value;
    this.apiClient = new AdminApiClient(
      () => this.adminKeyInput.value,
      () => this.gatewayKeyInput.value,
    );

    this.hydrateKeysFromQuery();
    this.saveAuthButton.addEventListener("click", () => {
      localStorage.setItem(ADMIN_KEY_STORAGE, this.adminKeyInput.value.trim());
      localStorage.setItem(GATEWAY_KEY_STORAGE, this.gatewayKeyInput.value.trim());
      this.pushAlert("Saved API keys in browser local storage.", "info");
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

  setHero(page: PageId): void {
    const meta = PAGE_META[page];
    this.pageEyebrow.textContent = meta.eyebrow;
    this.pageTitle.textContent = meta.title;
    this.pageSubtitle.textContent = meta.subtitle;
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
    const nextPath = pathForPage(page);
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (currentUrl !== nextPath) {
      window.history.pushState({}, "", nextPath);
    }
    void this.render(page);
  }

  saveGatewayKey(value: string): void {
    this.gatewayKeyInput.value = value;
    localStorage.setItem(GATEWAY_KEY_STORAGE, value);
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
            <pre class="code-block">${toErrorMessage(error)}</pre>
          </div>
        </article>
      `);
      this.pushAlert(
        "The current page failed to load. Check your admin API key or recent logs.",
        "danger",
      );
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

      this.modeChip.textContent = String(runtime.mode ?? "n/a");
      this.backendChip.textContent = String(runtime.gigachat_api_mode ?? "n/a");
      this.persistedChip.textContent = setup.persisted ? "persisted" : "defaults";

      if (!setup.persisted) {
        this.pushAlert(
          "Control-plane config is not persisted yet. Save settings to make zero-env restarts work.",
          "warn",
        );
      }
      if (!setup.gigachat_ready) {
        this.pushAlert(
          "GigaChat credentials are not configured yet. Playground calls will fail until the GigaChat section is filled.",
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
      if (runtime.mode === "DEV") {
        this.pushAlert(
          "Console is running in DEV mode. /admin and docs are available, which is convenient but not hardened.",
          "info",
        );
      }
    } catch (error) {
      this.pushAlert(`Failed to load global admin status. ${toErrorMessage(error)}`, "danger");
      this.modeChip.textContent = "error";
      this.backendChip.textContent = "error";
      this.persistedChip.textContent = "error";
    }
  }

  private hydrateKeysFromQuery(): void {
    const params = new URLSearchParams(window.location.search);
    const queryKey = params.get("x-api-key")?.trim();
    if (!queryKey) {
      return;
    }

    this.adminKeyInput.value = queryKey;
    localStorage.setItem(ADMIN_KEY_STORAGE, queryKey);

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

      event.preventDefault();
      const nextPage = pageFromLocation({
        hash: url.hash,
        pathname: url.pathname,
        search: url.search,
      } as Location);
      this.navigate(nextPage);
    });

    window.addEventListener("popstate", () => {
      void this.render();
    });
  }

  private setNav(page: PageId): void {
    this.nav.querySelectorAll("a[href]").forEach((link) => {
      const href = link.getAttribute("href");
      const matchesOverview = page === "overview" && (href === "/admin" || href === "/admin/overview");
      link.classList.toggle("active", matchesOverview || href === pathForPage(page));
    });
  }

  private requireElement<T extends HTMLElement>(id: string): T {
    const node = document.getElementById(id);
    if (!node) {
      throw new Error(`Missing required element #${id}`);
    }
    return node as T;
  }
}
