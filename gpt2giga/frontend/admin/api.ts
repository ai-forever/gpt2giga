export interface ApiRequestInit extends Omit<RequestInit, "body"> {
  json?: unknown;
  body?: BodyInit | null;
}

export class AdminApiClient {
  constructor(
    private readonly getAdminKey: () => string,
    private readonly getGatewayKey: () => string,
  ) {}

  async json<T>(path: string, init: ApiRequestInit = {}, useGateway = false): Promise<T> {
    const response = await this.raw(path, init, useGateway);
    return (await response.json()) as T;
  }

  async text(path: string, init: ApiRequestInit = {}, useGateway = false): Promise<string> {
    const response = await this.raw(path, init, useGateway);
    return response.text();
  }

  raw(path: string, init: ApiRequestInit = {}, useGateway = false): Promise<Response> {
    const headers = new Headers(init.headers ?? {});
    const key = (useGateway ? this.getGatewayKey() : this.getAdminKey()).trim();
    if (key) {
      headers.set("Authorization", `Bearer ${key}`);
    }

    let body = init.body ?? null;
    if (init.json !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(init.json);
    }

    return fetch(path, {
      ...init,
      headers,
      body,
    }).then(async (response) => {
      if (response.ok) {
        return response;
      }
      const text = await response.text();
      throw new Error(`${path} -> ${response.status}\n${text}`);
    });
  }
}
