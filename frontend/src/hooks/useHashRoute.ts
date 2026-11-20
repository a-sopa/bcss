import { useSyncExternalStore } from "react";

export type Route = { name: "home" } | { name: "console" } | { name: "editor"; appId: string };

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

let cached: { hash: string; route: Route } = { hash: "", route: { name: "home" } };

function parse(hash: string): Route {
  const editor = hash.match(/^#\/console\/apps\/([0-9a-f]{10})\/editor$/);
  if (editor) return { name: "editor", appId: editor[1] };
  if (hash.startsWith("#/console")) return { name: "console" };
  return { name: "home" }; // plain #section anchors stay on the landing page
}

function snapshot(): Route {
  const hash = window.location.hash;
  if (hash !== cached.hash) cached = { hash, route: parse(hash) };
  return cached.route;
}

export function useHashRoute(): Route {
  return useSyncExternalStore(subscribe, snapshot, () => ({ name: "home" }) as Route);
}

export const editorHref = (appId: string) => `#/console/apps/${appId}/editor`;
