import { describe, expect, it } from "vitest";

import {
  defaultDefinition,
  duplicateDefinition,
  parseScheduleContent,
  sourceFromDetail,
} from "./automation-authoring";

describe("Automation native authoring contracts", () => {
  it("builds editable starter definitions for every section", () => {
    expect(defaultDefinition("agents")).toMatchObject({ id: "new-agent" });
    expect(defaultDefinition("workflows").content).toContain("steps:");
    expect(parseScheduleContent(defaultDefinition("schedules").content)).toMatchObject({
      id: "new-schedule",
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
