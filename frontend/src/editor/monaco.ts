// Monaco (the editor behind VS Code and github.dev), bundled locally: no CDN, works offline and under a strict CSP.
import * as monaco from "monaco-editor";
import { loader } from "@monaco-editor/react";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import CssWorker from "monaco-editor/esm/vs/language/css/css.worker?worker";
import HtmlWorker from "monaco-editor/esm/vs/language/html/html.worker?worker";
import TsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";

self.MonacoEnvironment = {
  getWorker(_id: string, label: string) {
    if (label === "json") return new JsonWorker();
    if (["css", "scss", "less"].includes(label)) return new CssWorker();
    if (["html", "handlebars", "razor"].includes(label)) return new HtmlWorker();
    if (["typescript", "javascript"].includes(label)) return new TsWorker();
    return new EditorWorker();
  },
};

loader.config({ monaco });

// Projects are opened without their dependencies, so type errors would be noise next to the security colours.
for (const defaults of [monaco.languages.typescript.typescriptDefaults, monaco.languages.typescript.javascriptDefaults]) {
  defaults.setDiagnosticsOptions({ noSemanticValidation: true, noSyntaxValidation: false });
}

monaco.editor.defineTheme("owncloud-dark", {
  base: "vs-dark",
  inherit: true,
  rules: [
    { token: "comment", foreground: "5F7391", fontStyle: "italic" },
    { token: "keyword", foreground: "7FB2FF" },
    { token: "string", foreground: "6FE4D6" },
    { token: "number", foreground: "F5B85A" },
  ],
  colors: {
    "editor.background": "#040D22",
    "editorGutter.background": "#040D22",
    "editor.lineHighlightBackground": "#0C1E4066",
    "editor.lineHighlightBorder": "#00000000",
    "editorLineNumber.foreground": "#4A607E",
    "editorLineNumber.activeForeground": "#8B9BB4",
    "editor.selectionBackground": "#42D6C533",
    "editorCursor.foreground": "#42D6C5",
    "editorIndentGuide.background1": "#A0BEDC14",
    "editorWidget.background": "#071330",
    "editorWidget.border": "#A0BEDC26",
    "editorHoverWidget.background": "#071330",
    "editorHoverWidget.border": "#A0BEDC33",
    "scrollbarSlider.background": "#8B9BB422",
    "minimap.background": "#020817",
  },
});

monaco.editor.defineTheme("owncloud-light", {
  base: "vs",
  inherit: true,
  rules: [],
  colors: {
    "editor.background": "#FFFFFF",
    "editor.lineHighlightBackground": "#F3F7FC",
    "editorLineNumber.foreground": "#8B9BB4",
    "editorCursor.foreground": "#071330",
  },
});

export { monaco };
