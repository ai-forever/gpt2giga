import { describe, expect, it } from "vitest";

import {
  automationStarter,
  defaultDefinition,
  duplicateDefinition,
  parseScheduleContent,
  scheduleContentFromForm,
  scheduleFormFromContent,
  sourceFromDetail,
} from "./automation-authoring";

describe("Automation native authoring contracts", () => {
  it("builds editable starter definitions for every section", () => {
    expect(defaultDefinition("agents")).toMatchObject({ id: "code-reviewer" });
    expect(defaultDefinition("workflows")).toMatchObject({ id: "review-change" });
    expect(parseScheduleContent(defaultDefinition("schedules").content)).toMatchObject({
      id: "weekday-review",
      cadence: { kind: "rrule", rrule: "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR" },
      workspace_policy: "worktree",
    });
    expect(["agents", "workflows", "schedules"].map((section) => (
      automationStarter(section as "agents" | "workflows" | "schedules").sequence
    ))).toEqual([1, 2, 3]);
  });

  it("round-trips the schedule wizard without losing advanced policy", () => {
    const source = JSON.stringify({
      id: "weekly-review",
      title: "Weekly Review",
      target: { kind: "workflow", id: "review-change" },
      cadence: {
        kind: "rrule",
        timezone: "Europe/Moscow",
        start_at: "2026-07-25T09:00:00",
        rrule: "FREQ=WEEKLY;BYDAY=FR",
      },
      overlap_policy: "skip",
      notifications: { desktop: false },
      workspace_policy: "worktree",
    });
    const form = scheduleFormFromContent(source);
    const content = scheduleContentFromForm("weekly-review-copy", {
      ...form,
      desktopNotifications: true,
      weekday: "MO",
    });

    expect(form).toMatchObject({
      cadencePreset: "weekly",
      weekday: "FR",
      timezone: "Europe/Moscow",
    });
    expect(parseScheduleContent(content)).toMatchObject({
      id: "weekly-review-copy",
      cadence: { rrule: "FREQ=WEEKLY;BYDAY=MO" },
      overlap_policy: "skip",
      notifications: { desktop: true },
      workspace_policy: "worktree",
    });
  });

  it("projects exact revisions and creates independent duplicates", () => {
    const source = sourceFromDetail("workflows", {
      workflow: { id: "review", source_hash: "hash-1" },
      source: "id: review\ntitle: Review\nsteps: []\n",
    });
    expect(source).toMatchObject({ id: "review", sourceHash: "hash-1" });
    expect(duplicateDefinition("workflows", source)).toMatchObject({
      id: "review-copy",
      sourceHash: null,
    });
    expect(duplicateDefinition("workflows", source).content).toContain(
      "title: Review Copy",
    );
  });

  it("removes immutable schedule snapshot fields from duplicates", () => {
    const duplicate = duplicateDefinition("schedules", {
      id: "nightly",
      sourceHash: "hash-1",
      content: JSON.stringify({
        id: "nightly",
        title: "Nightly",
        source_hash: "hash-1",
        target_hash: "hash-2",
        target_snapshot: { secret: "retained" },
      }),
    });
    expect(parseScheduleContent(duplicate.content)).toEqual({
      id: "nightly-copy",
      title: "Nightly Copy",
    });
  });
});
