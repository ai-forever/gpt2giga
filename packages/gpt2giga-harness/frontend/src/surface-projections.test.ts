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
          prompt: "secret",
        })),
        project: { root: "/private/repo" },
      },
      {
        workflows: [{ id: "review", title: "Review", steps: [{ id: "one" }], prompt: "secret" }],
        runs: [{ workflow_id: "review", status: "passed", updated_at: "2026-07-16T10:00:00Z", inputs: { token: "secret" } }],
      },
      {
        schedules: [{ definition: { id: "nightly", title: "Nightly", target: { kind: "eval", id: "compat" }, prompt: "secret" }, state: { status: "enabled" }, preview: ["2026-07-17T00:00:00Z"], worker: { online: true } }],
      },
    );

    expect(projected.agents).toHaveLength(100);
    expect(projected.workflows[0]).toMatchObject({ id: "review", stepCount: 1, lastRunStatus: "passed" });
    expect(projected.schedules[0]).toMatchObject({ target: "eval:compat", workerOnline: true });
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
      { harnesses: [{ spec: { id: "echo", title: "Echo", kind: "local", command: ["secret"] }, availability: { status: "ready", reason: "available" } }] },
      { default_api_mode: "v2", default_model: "GigaChat", proxy_url: "http://private" },
      { servers: [{ descriptor: { id: "docs", title: "Docs", transport: "stdio", enabled: true, trusted: true, command: ["secret"] }, latest_probe: { status: "healthy" } }] },
    );

    expect(projected.harnesses[0]).toMatchObject({ id: "echo", status: "ready" });
    expect(projected.mcp[0]).toMatchObject({ id: "docs", status: "healthy" });
    expect(JSON.stringify(projected)).not.toContain("secret");
    expect(JSON.stringify(projected)).not.toContain("http://private");
  });

  it("projects selected-plan doctor status and bounded remedies", () => {
    const projected = projectDoctor({
      preflight: {
        readiness: {
          blocked: false,
          summary: { ready: 1, degraded: 1, blocked: 0 },
          plan: { harness_id: "echo", workspace: "/private/repo" },
          findings: [{ id: "route-v2", status: "degraded", summary: "Not probed", remediation: [{ message: "Run doctor", command: "giga doctor --json" }] }],
        },
      },
    });

    expect(projected).toMatchObject({ harnessId: "echo", status: "degraded", contentFree: true });
    expect(projected.findings.at(0)?.command).toBe("giga doctor --json");
    expect(JSON.stringify(projected)).not.toContain("/private/repo");
  });
});
