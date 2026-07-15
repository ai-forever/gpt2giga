import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";

import { mutateCockpit } from "../api";
import {
  LoadingRows,
  OperationalSurface,
  StatusBadge,
  type OperationalTab,
} from "../components/OperationalSurface";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import {
  evaluationSurfaceOptions,
  remainingRequestKeys,
} from "../remaining-request-graph";
import type { EvaluationProjection } from "../surface-projections";

const tabs: readonly OperationalTab[] = [
  { id: "arena", labelKey: "arena", href: "/cockpit-v2/evaluation/arena" },
  { id: "evals", labelKey: "evals", href: "/cockpit-v2/evaluation/evals" },
  { id: "baselines", labelKey: "baselines", href: "/cockpit-v2/evaluation/baselines" },
];

export function EvaluationSurface() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const search = useRouterState({ select: (state) => state.location.searchStr });
  const section = pathname.endsWith("/arena") ? "arena" : pathname.endsWith("/baselines") ? "baselines" : "evals";
  const selectedId = new URLSearchParams(search).get("selected");
  const query = useQuery(evaluationSurfaceOptions());
  return (
    <OperationalSurface
      activeTab={section}
      aside={<EvaluationDetail section={section} selectedId={selectedId} />}
      detailKey="evaluationDetailMigrated"
      eyebrowKey="evaluationEyebrow"
      tabs={tabs}
      titleKey="evaluation"
    >
      <EvaluationList section={section} query={query} selectedId={selectedId} />
    </OperationalSurface>
  );
}

function EvaluationList({ section, query, selectedId }: {
  section: "arena" | "evals" | "baselines";
  query: UseQueryResult<EvaluationProjection, Error>;
  selectedId: string | null;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  if (query.isPending) return <LoadingRows />;
  if (query.isError || query.data === undefined) return <div className="error-state">{message(locale, "boundedDataUnavailable")}</div>;
  const rows = section === "arena" ? query.data.arenas : query.data[section];
  return (
    <>
      <div className="operations-toolbar">
        <div><span className="section-kicker">{message(locale, section)}</span><strong>{rows.length} {message(locale, "retainedItems")}</strong></div>
        {section === "arena" ? <a className="primary-link" href="/arena">{message(locale, "newArena")}</a> : null}
      </div>
      {rows.length === 0 ? <div className="empty-state">{message(locale, section === "evals" ? "noEvaluationResults" : "noItems")}</div> : (
        <div className="operations-table" role="table">
          {section === "arena" ? query.data.arenas.map((item) => <a className={`operations-row ${selectedId === item.id ? "selected" : ""}`} href={`/cockpit-v2/evaluation/arena?selected=${encodeURIComponent(item.id)}`} key={item.id}><div><strong>{item.id}</strong><span>{item.harnessCount} {message(locale, "harnesses")}</span></div><span>{item.createdAt}</span><span>{item.updatedAt}</span><StatusBadge status={item.status} /></a>) : null}
          {section === "evals" ? query.data.evals.map((item) => <a className={`operations-row ${selectedId === item.name ? "selected" : ""}`} href={`/cockpit-v2/evaluation/evals?selected=${encodeURIComponent(item.name)}`} key={item.name}><div><strong>{item.name}</strong><span>{item.description}</span></div><span>{item.caseCount} {message(locale, "cases")}</span><span>{item.latestScore ?? "—"}</span><StatusBadge status={item.latestStatus ?? "not run"} /></a>) : null}
          {section === "baselines" ? query.data.baselines.map((item) => <a className={`operations-row ${selectedId === item.specName ? "selected" : ""}`} href={`/cockpit-v2/evaluation/baselines?selected=${encodeURIComponent(item.specName)}`} key={item.specName}><div><strong>{item.specName}</strong><span>{item.evalRunId}</span></div><span>{item.pinnedAt ?? "—"}</span><span>{message(locale, "reviewedIntent")}</span><StatusBadge status="pinned" /></a>) : null}
        </div>
      )}
    </>
  );
}

function EvaluationDetail({ section, selectedId }: { section: "arena" | "evals" | "baselines"; selectedId: string | null }) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const query = useQuery(evaluationSurfaceOptions());
  const queryClient = useQueryClient();
  const selected = useMemo(() => {
    if (section === "arena") return query.data?.arenas.find((item) => item.id === selectedId);
    if (section === "baselines") return query.data?.baselines.find((item) => item.specName === selectedId);
    return query.data?.evals.find((item) => item.name === selectedId);
  }, [query.data, section, selectedId]);
  const runEval = useMutation({
    mutationFn: async () => {
      if (section !== "evals" || selected === undefined || !("name" in selected)) throw new Error("Select an eval first");
      return mutateCockpit(`/api/evals/${encodeURIComponent(selected.name)}/runs`, { dry_run: true });
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: remainingRequestKeys.evaluation() }),
  });
  const pinBaseline = useMutation({
    mutationFn: async () => {
      if (section !== "evals" || selected === undefined || !("latestRunId" in selected) || selected.latestRunId === null) throw new Error("A completed eval run is required");
      return mutateCockpit(`/api/evaluate/runs/${encodeURIComponent(selected.latestRunId)}/baseline`, {});
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: remainingRequestKeys.evaluation() }),
  });
  if (selected === undefined) return <div className="detail-empty"><span className="section-kicker">{message(locale, "selectedEvidence")}</span><h2>{message(locale, "selectEvaluationEvidence")}</h2><p>{message(locale, "evaluationSelectionHint")}</p></div>;
  return (
    <div className="definition-detail">
      <span className="section-kicker">{message(locale, "selectedEvidence")}</span>
      <h2>{"name" in selected ? selected.name : "specName" in selected ? selected.specName : selected.id}</h2>
      <dl className="compact-fields">{Object.entries(selected).slice(0, 7).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value === null ? "—" : String(value)}</dd></div>)}</dl>
      {section === "evals" ? <div className="stacked-actions"><button className="primary-button" disabled={runEval.isPending} onClick={() => runEval.mutate()} type="button">{message(locale, "runDryEval")}</button><button disabled={pinBaseline.isPending || !("latestRunId" in selected) || selected.latestRunId === null} onClick={() => pinBaseline.mutate()} type="button">{message(locale, "pinBaseline")}</button></div> : null}
      {runEval.isError || pinBaseline.isError ? <p className="mutation-error" role="alert">{runEval.error?.message ?? pinBaseline.error?.message}</p> : null}
      {runEval.isSuccess || pinBaseline.isSuccess ? <p className="mutation-success" role="status">{message(locale, "operationAccepted")}</p> : null}
    </div>
  );
}
