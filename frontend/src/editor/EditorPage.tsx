import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import { monaco } from "./monaco";
import { api, SEVERITIES, type CloudApp, type CodeFinding, type Severity, type SourceFile } from "../lib/api";
import { Brand, cx } from "../components/ui";
import { FileTree } from "./FileTree";
import { FindingsPanel } from "./FindingsPanel";
import { SEVERITY_META, SeveritySwatch } from "./severity";

type Buffer = { content: string; saved: string; language: string };
type Theme = "dark" | "light";

const ANALYSE_DELAY_MS = 600;
const THEME_KEY = "owncloud.editor.theme";

function worst(findings: CodeFinding[]): Severity | null {
  let level = -1;
  for (const f of findings) level = Math.max(level, SEVERITIES.indexOf(f.severity));
  return level >= 0 ? SEVERITIES[level] : null;
}

/** Monaco renders hover text as Markdown (HTML disabled); escape so code from the project is shown literally. */
function md(text: string) {
  return text.replace(/[\\`*_{}[\]()#+\-.!|<>]/g, "\\$&");
}

function readTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export default function EditorPage({ appId }: { appId: string }) {
  const [app, setApp] = useState<CloudApp | null>(null);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [findings, setFindings] = useState<CodeFinding[]>([]);
  const [quantumStatus, setQuantumStatus] = useState<string>("ok");
  const [openPath, setOpenPath] = useState<string | null>(null);
  const [buffers, setBuffers] = useState<Record<string, Buffer>>({});
  const [stale, setStale] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(readTheme);

  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const decorations = useRef<ReturnType<Parameters<OnMount>[0]["createDecorationsCollection"]> | null>(null);
  const findingsRef = useRef(findings);
  findingsRef.current = findings;
  const openRef = useRef(openPath);
  openRef.current = openPath;
  const buffersRef = useRef(buffers);
  buffersRef.current = buffers;
  const analyseTimer = useRef<number | undefined>(undefined);
  const analyseSeq = useRef(0);
  const pendingReveal = useRef<CodeFinding | null>(null);

  // ---------------------------------------------------------------- loading
  useEffect(() => {
    (async () => {
      try {
        const [appData, fileList, analysis] = await Promise.all([api.app(appId), api.files(appId), api.analysis(appId)]);
        setApp(appData);
        setFiles(fileList.files);
        setFindings(analysis.findings);
        setQuantumStatus(analysis.quantum);
        const first = analysis.findings[0]?.file ?? fileList.files.find((f) => f.language !== "plaintext")?.path ?? fileList.files[0]?.path;
        if (first) void openFile(first);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appId]);

  const openFile = useCallback(
    async (path: string) => {
      if (!buffersRef.current[path]) {
        try {
          const file = await api.readFile(appId, path);
          setBuffers((b) => ({ ...b, [path]: { content: file.content, saved: file.content, language: file.language } }));
        } catch (e) {
          setStatus(e instanceof Error ? e.message : String(e));
          return;
        }
      }
      setOpenPath(path);
    },
    [appId],
  );

  const dirty = useMemo(
    () => new Set(Object.entries(buffers).filter(([, b]) => b.content !== b.saved).map(([p]) => p)),
    [buffers],
  );

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty.size) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // ---------------------------------------------------------------- live analysis
  const analyse = useCallback(
    (path: string, content: string) => {
      window.clearTimeout(analyseTimer.current);
      setStale(true);
      analyseTimer.current = window.setTimeout(async () => {
        const seq = ++analyseSeq.current;
        try {
          const result = await api.analyzeBuffer(appId, path, content);
          if (seq !== analyseSeq.current) return;
          setFindings((all) => [...all.filter((f) => f.file !== path), ...result.findings]);
          setQuantumStatus(result.quantum === "skipped" ? quantumStatus : result.quantum);
        } catch (e) {
          setStatus(e instanceof Error ? e.message : String(e));
        } finally {
          if (seq === analyseSeq.current) setStale(false);
        }
      }, ANALYSE_DELAY_MS);
    },
    [appId, quantumStatus],
  );

  const onChange = (value: string | undefined) => {
    const path = openRef.current;
    if (!path || value === undefined) return;
    setBuffers((b) => ({ ...b, [path]: { ...b[path], content: value } }));
    analyse(path, value);
  };

  // ---------------------------------------------------------------- decorations
  const fileFindings = useMemo(() => findings.filter((f) => f.file === openPath), [findings, openPath]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !decorations.current) return;
    const model = editor.getModel();
    if (!model) return;
    const lineCount = model.getLineCount();
    const byLine = new Map<number, Severity>();
    for (const f of fileFindings) {
      for (let line = f.line; line <= Math.min(f.end_line, lineCount); line++) {
        const current = byLine.get(line);
        if (!current || SEVERITIES.indexOf(f.severity) > SEVERITIES.indexOf(current)) byLine.set(line, f.severity);
      }
    }
    const lineDecorations = [...byLine.entries()].map(([line, severity]) => ({
      range: new monaco.Range(line, 1, line, 1),
      options: {
        isWholeLine: true,
        className: `sev-line sev-line-${severity}`,
        linesDecorationsClassName: `sev-gutter sev-gutter-${severity}`,
        overviewRuler: { color: severity === "critical" ? "#ffffff" : SEVERITY_META[severity].color, position: monaco.editor.OverviewRulerLane.Right },
        minimap: { color: severity === "critical" ? "#000000" : SEVERITY_META[severity].color, position: monaco.editor.MinimapPosition.Inline },
      },
    }));
    const spanDecorations = fileFindings
      .filter((f) => f.line <= lineCount)
      .map((f) => ({
        range: new monaco.Range(f.line, f.column, Math.min(f.end_line, lineCount), f.end_column),
        options: {
          inlineClassName: `sev-text sev-text-${f.severity}`,
          hoverMessage: [
            { value: `**${md(f.title)}** — ${SEVERITY_META[f.severity].label} (${md(SEVERITY_META[f.severity].meaning)})` },
            { value: md(f.message) },
            ...(f.suggestion ? [{ value: `Suggestion: ${md(f.suggestion)}` }] : []),
            ...(f.fix ? [{ value: "Quick fix available (Ctrl+.)" }] : []),
          ],
        },
      }));
    decorations.current.set([...lineDecorations, ...spanDecorations]);
  }, [fileFindings, openPath, buffers]);

  // Reveal a finding after switching files.
  useEffect(() => {
    const target = pendingReveal.current;
    const editor = editorRef.current;
    if (target && editor && target.file === openPath) {
      pendingReveal.current = null;
      editor.revealLineInCenter(target.line);
      editor.setSelection(new monaco.Range(target.line, target.column, target.end_line, target.end_column));
      editor.focus();
    }
  }, [openPath, buffers]);

  const goTo = (finding: CodeFinding) => {
    pendingReveal.current = finding;
    if (finding.file === openPath) {
      setBuffers((b) => ({ ...b })); // trigger the reveal effect
    } else {
      void openFile(finding.file);
    }
  };

  const applyFix = (finding: CodeFinding) => {
    const editor = editorRef.current;
    if (!editor || !finding.fix || finding.file !== openRef.current) return;
    const { line, column, end_line, end_column, text } = finding.fix;
    editor.pushUndoStop();
    editor.executeEdits("owncloud-fix", [{ range: new monaco.Range(line, column, end_line, end_column), text, forceMoveMarkers: true }]);
    editor.pushUndoStop();
    editor.focus();
  };

  // ---------------------------------------------------------------- saving
  const save = useCallback(
    async (paths: string[]) => {
      setStatus("Saving…");
      try {
        for (const path of paths) {
          const buffer = buffersRef.current[path];
          if (!buffer || buffer.content === buffer.saved) continue;
          await api.saveFile(appId, path, buffer.content);
          setBuffers((b) => ({ ...b, [path]: { ...b[path], saved: buffer.content } }));
        }
        setStatus("Saved");
        return true;
      } catch (e) {
        setStatus(e instanceof Error ? e.message : String(e));
        return false;
      }
    },
    [appId],
  );

  const saveAndRedeploy = async () => {
    if (await save(Object.keys(buffersRef.current))) {
      await api.redeploy(appId);
      setStatus("Saved — redeploying. Follow the progress in the console.");
    }
  };

  const onMount: OnMount = (editor) => {
    editorRef.current = editor;
    decorations.current = editor.createDecorationsCollection();
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      if (openRef.current) void save([openRef.current]);
    });
    setBuffers((b) => ({ ...b })); // paint decorations for the first file
  };

  // Quick fixes (lightbulb / Ctrl+.) for findings under the cursor.
  useEffect(() => {
    const provider = monaco.languages.registerCodeActionProvider("*", {
      provideCodeActions(model, range) {
        if (model !== editorRef.current?.getModel()) return { actions: [], dispose() {} };
        const actions = findingsRef.current
          .filter((f) => f.file === openRef.current && f.fix && f.line <= range.endLineNumber && f.end_line >= range.startLineNumber)
          .map((f) => ({
            title: `OwnCloud: ${f.title} → ${f.fix!.text.trim()}`,
            kind: "quickfix",
            isPreferred: true,
            edit: {
              edits: [
                {
                  resource: model.uri,
                  versionId: model.getVersionId(),
                  textEdit: {
                    range: new monaco.Range(f.fix!.line, f.fix!.column, f.fix!.end_line, f.fix!.end_column),
                    text: f.fix!.text,
                  },
                },
              ],
            },
          }));
        return { actions, dispose() {} };
      },
    });
    return () => provider.dispose();
  }, []);

  const changeTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* preference is optional */
    }
  };

  // ---------------------------------------------------------------- render
  const severities = useMemo(() => {
    const map: Record<string, Severity | null> = {};
    const counts: Record<string, number> = {};
    for (const f of findings) counts[f.file] = (counts[f.file] ?? 0) + 1;
    for (const file of files) map[file.path] = worst(findings.filter((f) => f.file === file.path));
    return { map, counts };
  }, [findings, files]);
  const totals = useMemo(
    () => Object.fromEntries(SEVERITIES.map((s) => [s, findings.filter((f) => f.severity === s).length])) as Record<Severity, number>,
    [findings],
  );
  const buffer = openPath ? buffers[openPath] : undefined;

  if (error) {
    return (
      <div className="grid min-h-screen place-items-center px-6 text-center">
        <div>
          <p className="text-danger">{error}</p>
          <a href="#/console" className="mt-4 inline-block text-sm text-muted hover:text-ink">← Back to the console</a>
        </div>
      </div>
    );
  }

  return (
    <div className={cx("flex h-screen flex-col", theme === "light" && "editor-light")}>
      <header className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line px-4 py-2.5">
        <Brand />
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted">
          <a href="#/console" className="hover:text-ink">console</a>
          <span>/</span>
          <span className="text-ink">{app?.name ?? "…"}</span>
          {openPath && (
            <>
              <span>/</span>
              <span className="truncate">{openPath}</span>
            </>
          )}
        </nav>

        <ul className="ml-auto flex flex-wrap items-center gap-3" aria-label="Severity legend">
          {SEVERITIES.map((s) => (
            <li key={s} className="flex items-center gap-1.5 text-[11px] text-muted" title={SEVERITY_META[s].meaning}>
              <SeveritySwatch severity={s} />
              {SEVERITY_META[s].label}
              <span className="font-mono text-ink/80">{totals[s]}</span>
            </li>
          ))}
        </ul>

        <div className="flex items-center gap-2">
          <button type="button" onClick={changeTheme} className="h-8 rounded-full border border-line px-3 text-xs text-muted hover:text-ink">
            {theme === "dark" ? "Light" : "Dark"} theme
          </button>
          <button
            type="button"
            disabled={!openPath || !dirty.has(openPath)}
            onClick={() => openPath && save([openPath])}
            className="h-8 rounded-full border border-line px-3 text-xs text-ink hover:border-teal/40 disabled:opacity-40"
          >
            Save
          </button>
          <button
            type="button"
            onClick={saveAndRedeploy}
            className="h-8 rounded-full bg-teal px-4 text-xs font-medium text-navy-950 hover:bg-teal-soft"
          >
            Save & redeploy
          </button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[230px_1fr] lg:grid-cols-[240px_1fr_360px]">
        <div className="hidden min-h-0 overflow-auto border-r border-line p-2 md:block">
          <FileTree
            files={files}
            open={openPath}
            severities={severities.map}
            counts={severities.counts}
            dirty={dirty}
            onOpen={(p) => void openFile(p)}
          />
        </div>

        <div className="flex min-h-0 flex-col">
          <select
            aria-label="Open file"
            value={openPath ?? ""}
            onChange={(e) => void openFile(e.target.value)}
            className="border-b border-line bg-navy-950 px-3 py-2 font-mono text-xs md:hidden"
          >
            {files.map((f) => (
              <option key={f.path} value={f.path}>
                {f.path}
              </option>
            ))}
          </select>
          <div className="min-h-[320px] flex-1">
            {buffer && openPath ? (
              <Editor
                path={`file:///${appId}/${openPath}`}
                defaultValue={buffer.content}
                language={buffer.language}
                theme={theme === "dark" ? "owncloud-dark" : "owncloud-light"}
                onMount={onMount}
                onChange={onChange}
                options={{
                  fontFamily: "JetBrains Mono Variable, ui-monospace, monospace",
                  fontSize: 13,
                  lineHeight: 21,
                  minimap: { enabled: true, renderCharacters: false },
                  smoothScrolling: true,
                  scrollBeyondLastLine: false,
                  renderLineHighlight: "line",
                  glyphMargin: false,
                  lineDecorationsWidth: 12,
                  padding: { top: 12 },
                  lightbulb: { enabled: monaco.editor.ShowLightbulbIconMode.OnCode },
                  automaticLayout: true,
                }}
              />
            ) : (
              <div className="grid h-full place-items-center text-sm text-muted">Select a file</div>
            )}
          </div>
          <footer className="flex items-center gap-4 border-t border-line px-4 py-1.5 font-mono text-[11px] text-muted">
            <span>{buffer?.language ?? ""}</span>
            <span>{stale ? "Analysing…" : `${fileFindings.length} finding(s) in this file`}</span>
            {quantumStatus === "unavailable" && <span className="text-warn">QuantumTrace unavailable</span>}
            {dirty.size > 0 && <span className="text-teal">{dirty.size} unsaved</span>}
            {status && <span className="ml-auto truncate">{status}</span>}
          </footer>
        </div>

        <div className="min-h-0 border-t border-line lg:border-t-0 lg:border-l">
          <FindingsPanel findings={findings} openPath={openPath} stale={stale} onGoTo={goTo} onApply={applyFix} />
        </div>
      </div>
    </div>
  );
}
