export class AdminApiClient {
    getAdminKey;
    getGatewayKey;
    constructor(getAdminKey, getGatewayKey) {
        this.getAdminKey = getAdminKey;
        this.getGatewayKey = getGatewayKey;
    }
    async json(path, init = {}, useGateway = false) {
        const response = await this.raw(path, init, useGateway);
        return (await response.json());
    }
    async text(path, init = {}, useGateway = false) {
        const response = await this.raw(path, init, useGateway);
        return response.text();
    }
    raw(path, init = {}, useGateway = false) {
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
