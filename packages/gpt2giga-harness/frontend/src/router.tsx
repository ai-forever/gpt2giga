import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";

import { AppShell } from "./AppShell";

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

const routes = [
  cockpitRoute,
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/work", component: workbenchComponent }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/work/$sessionId", component: workbenchComponent }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/runs", component: runsComponent }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/runs/$runId", component: runsComponent }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/automation", component: lazyRouteComponent(() => import("./surfaces/automation"), "AutomationSurface") }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/evaluation", component: lazyRouteComponent(() => import("./surfaces/evaluation"), "EvaluationSurface") }),
  createRoute({ getParentRoute: () => rootRoute, path: "/cockpit-v2/integrations", component: lazyRouteComponent(() => import("./surfaces/integrations"), "IntegrationsSurface") }),
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
