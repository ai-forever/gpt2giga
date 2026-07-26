export type MCPAuthoringTransport = "stdio" | "streamable_http" | "sse";

export type MCPAuthoringForm = {
  transport: MCPAuthoringTransport;
  executable: string;
  argvText: string;
  cwd: string;
  environmentText: string;
  url: string;
  headersText: string;
  authorizationEnvironment: string;
};

type SecretReference = {
  schema_version: 1;
  kind: "environment";
  name: string;
  service: null;
  account: null;
  expires_at: null;
  cache_ttl_seconds: 0;
};

export type MCPAuthoringConfiguration = {
  schema_version: 1;
  transport: MCPAuthoringTransport;
  stdio?: {
    executable: string;
    argv: string[];
    cwd: string | null;
    environment: Record<string, SecretReference>;
  };
  remote?: {
    url: string;
    headers: Record<string, SecretReference>;
    authorization?: SecretReference;
  };
};

const environmentName = /^[A-Za-z_][A-Za-z0-9_]{0,127}$/;
const headerName = /^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/;

export function supportedMCPTransports(
  targetId: string,
): [MCPAuthoringTransport, ...MCPAuthoringTransport[]] {
  if (targetId === "gemini-mcp") return ["stdio", "streamable_http", "sse"];
  return ["stdio", "streamable_http"];
}

export function supportsMCPAuthoringCwd(targetId: string) {
  return targetId === "codex-mcp"
    || targetId === "gemini-mcp"
    || targetId === "harness-managed-mcp";
}

export function buildMCPAuthoringConfiguration(
  form: MCPAuthoringForm,
): MCPAuthoringConfiguration {
  if (form.transport === "stdio") {
    const executable = form.executable.trim();
    if (!executable) throw new Error("MCP executable is required");
    const environment = Object.fromEntries(
      parseLines(form.environmentText).map((name) => {
        if (!environmentName.test(name)) throw new Error(`Invalid environment name: ${name}`);
        return [name, environmentSecretReference(name)];
      }),
    );
    return {
      schema_version: 1,
      transport: "stdio",
      stdio: {
        executable,
        argv: parseLines(form.argvText),
        cwd: form.cwd.trim() || null,
        environment,
      },
    };
  }
  const url = form.url.trim();
  if (!url) throw new Error("MCP HTTPS URL is required");
  const headers = Object.fromEntries(
    parseLines(form.headersText).map((line) => {
      const separator = line.indexOf("=");
      const name = separator >= 0 ? line.slice(0, separator).trim() : "";
      const environment = separator >= 0 ? line.slice(separator + 1).trim() : "";
      if (!headerName.test(name) || !environmentName.test(environment)) {
        throw new Error(`Invalid header reference: ${line}`);
      }
      return [name, environmentSecretReference(environment)];
    }),
  );
  const authorization = form.authorizationEnvironment.trim();
  if (authorization && !environmentName.test(authorization)) {
    throw new Error(`Invalid authorization environment: ${authorization}`);
  }
  return {
    schema_version: 1,
    transport: form.transport,
    remote: {
      url,
      headers,
      ...(authorization
        ? { authorization: environmentSecretReference(authorization) }
        : {}),
    },
  };
}

function parseLines(value: string) {
  const lines = value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (new Set(lines).size !== lines.length) throw new Error("MCP entries must be unique");
  return lines;
}

function environmentSecretReference(name: string): SecretReference {
  return {
    schema_version: 1,
    kind: "environment",
    name,
    service: null,
    account: null,
    expires_at: null,
    cache_ttl_seconds: 0,
  };
}
