import { useMemo, useState } from "react";
import type { Severity, SourceFile } from "../lib/api";
import { cx } from "../components/ui";
import { SeveritySwatch } from "./severity";

type Folder = { name: string; path: string; folders: Map<string, Folder>; files: SourceFile[] };

function buildTree(files: SourceFile[]): Folder {
  const root: Folder = { name: "", path: "", folders: new Map(), files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let folder = root;
    for (const part of parts.slice(0, -1)) {
      const path = folder.path ? `${folder.path}/${part}` : part;
      if (!folder.folders.has(part)) folder.folders.set(part, { name: part, path, folders: new Map(), files: [] });
      folder = folder.folders.get(part)!;
    }
    folder.files.push(file);
  }
  return root;
}

type Props = {
  files: SourceFile[];
  open: string | null;
  severities: Record<string, Severity | null>;
  counts: Record<string, number>;
  dirty: Set<string>;
  onOpen: (path: string) => void;
};

export function FileTree({ files, open, severities, counts, dirty, onOpen }: Props) {
  const tree = useMemo(() => buildTree(files), [files]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggle = (path: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const renderFolder = (folder: Folder, depth: number) => (
    <>
      {[...folder.folders.values()]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((child) => (
          <li key={child.path}>
            <button
              type="button"
              onClick={() => toggle(child.path)}
              aria-expanded={!collapsed.has(child.path)}
              className="flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-[13px] text-muted hover:bg-white/[0.04] hover:text-ink"
              style={{ paddingLeft: 8 + depth * 14 }}
            >
              <span className={cx("inline-block w-3 text-[10px] transition-transform", !collapsed.has(child.path) && "rotate-90")}>
                ▸
              </span>
              {child.name}
            </button>
            {!collapsed.has(child.path) && <ul>{renderFolder(child, depth + 1)}</ul>}
          </li>
        ))}
      {[...folder.files]
        .sort((a, b) => a.path.localeCompare(b.path))
        .map((file) => {
          const name = file.path.split("/").pop();
          const severity = severities[file.path];
          return (
            <li key={file.path}>
              <button
                type="button"
                onClick={() => onOpen(file.path)}
                aria-current={open === file.path ? "page" : undefined}
                title={file.path}
                className={cx(
                  "flex w-full items-center gap-2 rounded-md py-1 pr-2 text-left text-[13px] transition-colors",
                  open === file.path ? "bg-white/[0.08] text-ink" : "text-ink/75 hover:bg-white/[0.04] hover:text-ink",
                )}
                style={{ paddingLeft: 22 + depth * 14 }}
              >
                <span className="min-w-0 flex-1 truncate">
                  {name}
                  {dirty.has(file.path) && <span className="ml-1 text-teal" aria-label="unsaved">●</span>}
                </span>
                {severity && (
                  <span className="flex items-center gap-1 font-mono text-[10px] text-muted">
                    {counts[file.path]}
                    <SeveritySwatch severity={severity} />
                  </span>
                )}
              </button>
            </li>
          );
        })}
    </>
  );

  return (
    <nav aria-label="Project files">
      <ul className="space-y-px">{renderFolder(tree, 0)}</ul>
    </nav>
  );
}
