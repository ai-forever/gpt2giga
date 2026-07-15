import { useParams } from "@tanstack/react-router";

import { useVisibleRunReadModel } from "../read-model";
import { useRunEventStream } from "../stream-store";
import { SurfaceScaffold } from "./SurfaceScaffold";

export function RunsSurface() {
  const params = useParams({ strict: false });
  const runId =
    "runId" in params && typeof params.runId === "string" ? params.runId : undefined;
  const readModelState = useVisibleRunReadModel(runId);
  const streamState = useRunEventStream(runId);
  return (
    <SurfaceScaffold
      detailKey="runsDetail"
      eyebrowKey="runsEyebrow"
      readModelState={readModelState}
      streamState={streamState}
      titleKey="runs"
    />
  );
}
