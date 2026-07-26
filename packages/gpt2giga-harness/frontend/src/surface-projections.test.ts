import { describe, expect, it } from "vitest";

import {
  projectAutomation,
  projectDoctor,
  projectEvaluation,
  projectIntegrations,
} from "./surface-projections";

describe("remaining Cockpit surface projections", () => {
  it("keeps automation state bounded and content-free", () => {
    const projected = projectAutomation(
      {
        agents: Array.from({ length: 101 }, (_, index) => ({
          id: `reviewer-${index}`,
          title: "Reviewer",
          harness_id: "echo",
          execution_plan: { queueable: true, errors: [] },
          prompt: "secret",
        })),
        project: { root: "/private/repo" },
      },
      {
        workflows: [{ id: "review", title: "Review", steps: [{ id: "one" }], prompt: "secret" }],
        runs: [{ workflow_id: "review", status: "running", updated_at: "2026-07-16T10:00:00Z", inputs: { token: "secret" } }],
      },
      {
        schedules: [{ definition: { id: "nightly", title: "Nightly", source_hash: "hash-1", target: { kind: "eval", id: "compat" }, prompt: "secret" }, state: { status: "enabled", tested_hash: "hash-1" }, preview: ["2026-07-17T00:00:00Z"], worker: { online: true } }],
        worker: { online: true, count: 1 },
      },
    );

    expect(projected.agents).toHaveLength(100);
    expect(projected.workflows[0]).toMatchObject({ id: "review", stepCount: 1, lastRunStatus: "running", workerOnline: true });
    expect(projected.agents[0]).toMatchObject({ queueable: true, unavailableReason: null });
    expect(projected.schedules[0]).toMatchObject({ target: "eval:compat", workerOnline: true, tested: true });
    expect(projected.workerOnline).toBe(true);
    expect(JSON.stringify(projected)).not.toContain("secret");
    expect(JSON.stringify(projected)).not.toContain("/private/repo");
  });

  it("projects evaluation identities without prompts or project roots", () => {
    const projected = projectEvaluation(
      {
        quality_specs: [{ name: "compat", description: "Compatibility", case_count: 3, baseline: { eval_run_id: "eval_base", pinned_at: "now" } }],
        runs: [{ id: "eval_latest", spec_name: "compat", status: "failed", summary: { score: 0.5 }, project_root: "/private/repo" }],
      },
      { arenas: [{ id: "arena_1", status: "passed", harness_ids: ["echo"], prompt: "secret", created_at: "then", updated_at: "now" }] },
    );

    expect(projected.evals[0]).toMatchObject({ latestRunId: "eval_latest", baselineRunId: "eval_base" });
    expect(projected.arenas[0]).toMatchObject({ id: "arena_1", harnessCount: 1 });
    expect(JSON.stringify(projected)).not.toContain("secret");
    expect(JSON.stringify(projected)).not.toContain("/private/repo");
  });

  it("projects integration readiness without commands, urls, or secrets", () => {
    const projected = projectIntegrations(
      { harnesses: [{ spec: { id: "claude-code", title: "Claude Code", kind: "agent-cli", command: ["secret"] }, availability: { status: "ready", reason: "available" }, execution_surfaces: [{ id: "provider_handoff", status: "degraded", ownership: "provider_owned", queueable: false, detail: "Claude owns the session", blocker: null }, { id: "native_structured_embedded", status: "blocked", ownership: "unavailable", queueable: false, detail: "Embedding unavailable", blocker: "approval_not_accepted" }], provider_handoff: { available_actions: ["launch_new", "attach_current"], degraded_actions: ["open_provider_ui"] } }] },
      { routes: { default_api_mode: "v2", default_model: "GigaChat-2-Max", default_model_source: "built_in" }, runtime: { proxy_url: "http://private" } },
      [
        { api_mode: "v1", health: "blocked", last_checked_at: "2026-07-16T18:00:00Z", models: [], route_path: "/v1/models", source: "/v1/models" },
        { api_mode: "v2", health: "ready", last_checked_at: "2026-07-16T18:00:01Z", models: ["GigaChat-3", "GigaChat-2-Max"], route_path: "/v2/models", source: "/v2/models" },
      ],
      { servers: [{ descriptor: { id: "docs", title: "Docs", transport: "stdio", enabled: true, trusted: true, command: ["secret"] }, latest_probe: { status: "healthy" } }] },
    );

    expect(projected.harnesses[0]).toMatchObject({
      id: "claude-code",
      status: "ready",
      handoffActions: ["launch_new", "attach_current", "open_provider_ui"],
      executionSurfaces: [
        { id: "provider_handoff", ownership: "provider_owned", queueable: false },
        { id: "native_structured_embedded", status: "blocked", blocker: "approval_not_accepted" },
      ],
    });
    expect(projected.routes).toHaveLength(2);
    expect(projected.routes[0]).toMatchObject({ apiMode: "v1", configuredDefault: false, effectiveModel: null, health: "blocked" });
    expect(projected.routes[1]).toMatchObject({
      apiMode: "v2",
      chatEndpoint: "/v2/chat/completions",
      configuredDefault: true,
      effectiveModel: "GigaChat-2-Max",
      effectiveSource: "built_in",
      discoveredModels: ["GigaChat-3", "GigaChat-2-Max"],
      health: "ready",
    });
    expect(projected.mcp[0]).toMatchObject({ id: "docs", status: "healthy" });
    expect(JSON.stringify(projected)).not.toContain("secret");
    expect(JSON.stringify(projected)).not.toContain("http://private");
  });

  it("projects selected-plan doctor status and bounded remedies", () => {
    const projected = projectDoctor({
      preflight: {
        readiness: {
          blocked: false,
          schema_version: 2,
          status: "ready",
          evidence_status: "not_checked",
          summary: { ready: 1, not_checked: 1, unknown: 0, degraded: 0, blocked: 0 },
          plan: { harness_id: "echo", workspace: "/private/repo" },
          findings: [{ id: "route-v2", status: "not_checked", summary: "Not probed", remediation: [{ message: "Run doctor", command: "giga doctor --json" }] }],
        },
      },
    });

    expect(projected).toMatchObject({ harnessId: "echo", status: "ready", evidenceStatus: "not_checked", contentFree: true });
    expect(projected.findings.at(0)?.command).toBe("giga doctor --json");
    expect(JSON.stringify(projected)).not.toContain("/private/repo");
  });
});
