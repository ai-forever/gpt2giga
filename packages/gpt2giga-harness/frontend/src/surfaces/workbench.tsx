import { useParams } from "@tanstack/react-router";

import { useVisibleSessionReadModel } from "../read-model";
import { SurfaceScaffold } from "./SurfaceScaffold";

export function WorkbenchSurface() {
  const params = useParams({ strict: false });
  const sessionId =
    "sessionId" in params && typeof params.sessionId === "string"
      ? params.sessionId
      : undefined;
  const readModelState = useVisibleSessionReadModel(sessionId);
  return (
    <SurfaceScaffold
      detailKey="workbenchDetail"
      eyebrowKey="workbenchEyebrow"
      readModelState={readModelState}
      titleKey="workbench"
    />
  );
}
