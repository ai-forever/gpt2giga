import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";

import { AppShell } from "./AppShell";
import { validateOperationalSearch } from "./operational-navigation";
import { validateWorkbenchEntrySearch } from "./session-creation";

const rootRoute = createRootRoute({ component: AppShell });

const cockpitRoute = createRoute({
  beforeLoad: () => {
    throw redirect({ to: "/cockpit-v2/work" });
  },
  getParentRoute: () => rootRoute,
  path: "/cockpit-v2",
});

const workbenchComponent = lazyRouteComponent(
  () => import("./surfaces/workbench"),
  "WorkbenchSurface",
);
const runsComponent = lazyRouteComponent(() => import("./surfaces/runs"), "RunsSurface");
const automationComponent = lazyRouteComponent(() => import("./surfaces/automation"), "AutomationSurface");
const evaluationComponent = lazyRouteComponent(() => import("./surfaces/evaluation"), "EvaluationSurface");
const integrationsComponent = lazyRouteComponent(() => import("./surfaces/integrations"), "IntegrationsSurface");

const routes = [
  cockpitRoute,
  createRoute({
    component: workbenchComponent,
    getParentRoute: () => rootRoute,
    path: "/cockpit-v2/work",
    validateSearch: validateWorkbenchEntrySearch,
  }),
  createRoute({
    component: workbenchComponent,
    getParentRoute: () => rootRoute,
    path: "/cockpit-v2/work/$sessionId",
    validateSearch: validateWorkbenchEntrySearch,
  }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/runs", component: runsComponent }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/runs/$runId", component: runsComponent }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/automation/workflows" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/automation" }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/automation/agents", component: automationComponent, validateSearch: validateOperationalSearch }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/automation/workflows", component: automationComponent, validateSearch: validateOperationalSearch }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/automation/schedules", component: automationComponent, validateSearch: validateOperationalSearch }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/evaluation/evals" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/evaluation" }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/evaluation/arena", component: evaluationComponent, validateSearch: validateOperationalSearch }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/evaluation/evals", component: evaluationComponent, validateSearch: validateOperationalSearch }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/evaluation/baselines", component: evaluationComponent, validateSearch: validateOperationalSearch }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/plugins/all" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/plugins" }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/plugins/all", component: integrationsComponent, validateSearch: validateOperationalSearch }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/plugins/mcp", component: integrationsComponent, validateSearch: validateOperationalSearch }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/plugins/plugins", component: integrationsComponent, validateSearch: validateOperationalSearch }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/plugins/skills", component: integrationsComponent, validateSearch: validateOperationalSearch }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/plugins/all" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/integrations" }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/plugins/all" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/integrations/harnesses" }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/plugins/all" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/integrations/models" }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/plugins/mcp" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/integrations/mcp" }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/plugins/all" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/integrations/add" }),
  createRoute({ beforeLoad: () => { throw redirect({ to: "/cockpit-v2/plugins/all" }); }, getParentRoute: () => rootRoute, path: "/cockpit-v2/integrations/doctor" }),
  createRoute({
    getParentRoute: () => rootRoute,
    path: "/cockpit-v2/settings",
    component: lazyRouteComponent(
      () => import("./surfaces/settings"),
      "SettingsSurface",
    ),
  }),
];

const routeTree = rootRoute.addChildren(routes);

export const router = createRouter({
  defaultPreload: "intent",
  routeTree,
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
