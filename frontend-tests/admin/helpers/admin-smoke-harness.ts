import { readFileSync } from "node:fs";

import { JSDOM } from "jsdom";

import { AdminApp } from "../../../gpt2giga/frontend/admin/app.js";

type RouteResponse =
  | Response
  | {
      body?: BodyInit | null;
      headers?: HeadersInit;
      json?: unknown;
      status?: number;
      text?: string;
    };

type RouteHandler = (
  request: Request,
  url: URL,
) => Promise<RouteResponse> | RouteResponse;

export interface AdminSmokeHarness {
  app: AdminApp;
  cleanup: () => void;
  document: Document;
  pageContent: HTMLElement;
  waitFor: (predicate: () => boolean, label: string) => Promise<void>;
  window: Window;
}

interface CreateAdminSmokeHarnessOptions {
  path: string;
  routes: Record<string, RouteHandler | RouteResponse>;
}

const CONSOLE_TEMPLATE = readFileSync(
  new URL(
    "../../../packages/gpt2giga-ui/src/gpt2giga_ui/templates/console.html",
    import.meta.url,
  ),
  "utf-8",
);

const GLOBAL_KEYS = [
  "window",
  "document",
  "navigator",
  "location",
  "history",
  "sessionStorage",
  "localStorage",
  "HTMLElement",
  "Element",
  "Node",
  "Document",
  "Event",
  "CustomEvent",
  "MouseEvent",
  "KeyboardEvent",
  "HTMLAnchorElement",
  "HTMLButtonElement",
  "HTMLDetailsElement",
  "HTMLFormElement",
  "HTMLInputElement",
  "HTMLSelectElement",
  "HTMLTextAreaElement",
  "AbortController",
  "fetch",
].map((key) => key as keyof typeof globalThis);

export function createAdminSmokeHarness(
  options: CreateAdminSmokeHarnessOptions,
): AdminSmokeHarness {
  const dom = new JSDOM(CONSOLE_TEMPLATE, {
    pretendToBeVisual: true,
    url: `http://localhost:8090${options.path}`,
  });
  const { window } = dom;
  const previousGlobals = new Map<keyof typeof globalThis, unknown>();

  window.matchMedia = ((query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList) as typeof window.matchMedia;
  window.scrollTo = () => {};
  window.confirm = () => true;

  const fetchImpl = async (
    input: string | URL | Request,
    init?: RequestInit,
  ): Promise<Response> => {
    const baseUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    const requestUrl = new URL(baseUrl, window.location.origin);
    const method =
      init?.method ??
      (input instanceof Request ? input.method : undefined) ??
      "GET";
    const request = new Request(requestUrl.toString(), {
      ...init,
      method,
    });
    const routeKey = `${method.toUpperCase()} ${requestUrl.pathname}${requestUrl.search}`;
    const route = options.routes[routeKey];
    if (!route) {
      throw new Error(`Unexpected fetch: ${routeKey}`);
    }
    const result =
      typeof route === "function"
        ? await route(request, requestUrl)
        : route;
    return toResponse(result);
  };

  window.fetch = fetchImpl as typeof window.fetch;

  for (const key of GLOBAL_KEYS) {
    previousGlobals.set(key, globalThis[key]);
  }

  setGlobal("window", window);
  setGlobal("document", window.document);
  setGlobal("navigator", window.navigator);
  setGlobal("location", window.location);
  setGlobal("history", window.history);
  setGlobal("sessionStorage", window.sessionStorage);
  setGlobal("localStorage", window.localStorage);
  setGlobal("HTMLElement", window.HTMLElement);
  setGlobal("Element", window.Element);
  setGlobal("Node", window.Node);
  setGlobal("Document", window.Document);
  setGlobal("Event", window.Event);
  setGlobal("CustomEvent", window.CustomEvent);
  setGlobal("MouseEvent", window.MouseEvent);
  setGlobal("KeyboardEvent", window.KeyboardEvent);
  setGlobal("HTMLAnchorElement", window.HTMLAnchorElement);
  setGlobal("HTMLButtonElement", window.HTMLButtonElement);
  setGlobal("HTMLDetailsElement", window.HTMLDetailsElement);
  setGlobal("HTMLFormElement", window.HTMLFormElement);
  setGlobal("HTMLInputElement", window.HTMLInputElement);
  setGlobal("HTMLSelectElement", window.HTMLSelectElement);
  setGlobal("HTMLTextAreaElement", window.HTMLTextAreaElement);
  setGlobal("AbortController", window.AbortController);
  setGlobal("fetch", fetchImpl);

  return {
    app: new AdminApp(),
    cleanup: () => {
      for (const [key, value] of previousGlobals.entries()) {
        setGlobal(key, value);
      }
      window.close();
    },
    document: window.document,
    pageContent: window.document.getElementById("page-content") as HTMLElement,
    waitFor: async (predicate: () => boolean, label: string) => {
      for (let attempt = 0; attempt < 40; attempt += 1) {
        if (predicate()) {
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 0));
      }
      throw new Error(`Timed out waiting for ${label}`);
    },
    window,
  };
}

function setGlobal(
  key: keyof typeof globalThis,
  value: unknown,
): void {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value,
    writable: true,
  });
}

function toResponse(value: RouteResponse): Response {
  if (value instanceof Response) {
    return value;
  }
  if (value.json !== undefined) {
    return new Response(JSON.stringify(value.json), {
      headers: {
        "content-type": "application/json",
        ...value.headers,
      },
      status: value.status ?? 200,
    });
  }
  return new Response(value.body ?? value.text ?? null, {
    headers: value.headers,
    status: value.status ?? 200,
  });
}
