import { describe, expect, it } from "vitest";

import {
  buildMCPAuthoringConfiguration,
  supportedMCPTransports,
  supportsMCPAuthoringCwd,
} from "./mcp-authoring-model";

describe("MCP authoring model", () => {
  it("builds separate stdio executable, argv, cwd, and secret references", () => {
    const configuration = buildMCPAuthoringConfiguration({
      transport: "stdio",
      executable: "fixture-mcp",
      argvText: "--stdio\n--quiet",
      cwd: "tools/server",
      environmentText: "MCP_TOKEN",
      url: "",
      headersText: "",
      authorizationEnvironment: "",
    });

    expect(configuration).toMatchObject({
      schema_version: 1,
      transport: "stdio",
      stdio: {
        executable: "fixture-mcp",
        argv: ["--stdio", "--quiet"],
        cwd: "tools/server",
        environment: {
          MCP_TOKEN: { kind: "environment", name: "MCP_TOKEN" },
        },
      },
    });
    expect(configuration.remote).toBeUndefined();
  });

  it("builds remote URL, bounded header references, and authorization separately", () => {
    const configuration = buildMCPAuthoringConfiguration({
      transport: "streamable_http",
      executable: "",
      argvText: "",
      cwd: "",
      environmentText: "",
      url: "https://mcp.example/v1?tenant=fixture",
      headersText: "X-Tenant=TENANT_ID",
      authorizationEnvironment: "MCP_AUTHORIZATION",
    });

    expect(configuration).toMatchObject({
      schema_version: 1,
      transport: "streamable_http",
      remote: {
        url: "https://mcp.example/v1?tenant=fixture",
        headers: {
          "X-Tenant": { kind: "environment", name: "TENANT_ID" },
        },
        authorization: {
          kind: "environment",
          name: "MCP_AUTHORIZATION",
        },
      },
    });
    expect(configuration.stdio).toBeUndefined();
  });

  it("projects target transport and cwd capabilities without impossible choices", () => {
    expect(supportedMCPTransports("gemini-mcp")).toEqual([
      "stdio",
      "streamable_http",
      "sse",
    ]);
    expect(supportedMCPTransports("claude-mcp")).toEqual([
      "stdio",
      "streamable_http",
    ]);
    expect(supportsMCPAuthoringCwd("claude-mcp")).toBe(false);
    expect(supportsMCPAuthoringCwd("codex-mcp")).toBe(true);
  });
});
