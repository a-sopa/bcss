import { useSyncExternalStore } from "react";
import type { LayoutName } from "../lib/network";

const QUERIES: [LayoutName, string][] = [
  ["mobile", "(max-width: 639px)"],
  ["tablet", "(max-width: 1023px)"],
];

function current(): LayoutName {
  return QUERIES.find(([, query]) => window.matchMedia(query).matches)?.[0] ?? "desktop";
}

function subscribe(onChange: () => void) {
  const lists = QUERIES.map(([, query]) => window.matchMedia(query));
  lists.forEach((list) => list.addEventListener("change", onChange));
  return () => lists.forEach((list) => list.removeEventListener("change", onChange));
}

export function useLayout(): LayoutName {
  return useSyncExternalStore(subscribe, current, () => "desktop");
}
