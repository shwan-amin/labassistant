// VS Code wiring: the command, consent, collecting files, diagnostics and the panel.
// Logic that doesn't need VS Code lives in the other modules so it can be unit tested.

import * as crypto from "crypto";
import * as vscode from "vscode";
import { ApiClient, ApiError } from "./api";
import { diagnosticsFor } from "./diagnostics";
import { isSafeExternalUrl } from "./html";
import { initialPanelState, MaterialWithImage, PanelState, renderPanel } from "./panelHtml";
import { CandidateFile, collectFiles, findProjectRoot, IGNORED_DIRS, PROJECT_MARKERS } from "./projectFiles";
import { Material } from "./types";

const CONSENT_KEY = "labAssistant.consentGiven";
const MAX_FILES = 3000;

/** Options for running the command programmatically (keybindings, automated tests). */
export interface CheckOptions {
  explanation?: string; // when given, the explanation prompt is skipped
}

/** Returned from activate() so the end-to-end tests can drive and inspect the extension. */
export interface LabAssistantTestApi {
  state(): PanelState;
  answer(gapIndex: number, answer: string): Promise<void>;
  setConsent(given: boolean): Thenable<void>;
}

export function activate(context: vscode.ExtensionContext): LabAssistantTestApi {
  const controller = new Controller(context);
  context.subscriptions.push(
    controller.diagnostics,
    controller.statusBar,
    vscode.commands.registerCommand("labAssistant.checkUnderstanding", (arg?: unknown) => controller.check(asCheckOptions(arg))),
    vscode.commands.registerCommand("labAssistant.showPanel", () => controller.showPanel()),
    vscode.commands.registerCommand("labAssistant.resetConsent", async () => {
      await context.globalState.update(CONSENT_KEY, undefined);
      vscode.window.showInformationMessage("Lab Assistant will ask for consent again before sending code.");
    }),
  );
  return {
    state: () => controller.currentState,
    answer: (gapIndex, answer) => controller.answer(gapIndex, answer),
    setConsent: (given) => context.globalState.update(CONSENT_KEY, given || undefined),
  };
}

/** The context menu passes the file's Uri as an argument; only plain option objects count. */
function asCheckOptions(arg: unknown): CheckOptions {
  if (arg && typeof arg === "object" && !(arg instanceof vscode.Uri) && "explanation" in arg) {
    const explanation = (arg as { explanation: unknown }).explanation;
    return typeof explanation === "string" ? { explanation } : {};
  }
  return {};
}

export function deactivate(): void {}

class Controller {
  readonly diagnostics = vscode.languages.createDiagnosticCollection("labAssistant");
  readonly statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  private panel: vscode.WebviewPanel | undefined;
  private state: PanelState = initialPanelState();
  private projectRoot: vscode.Uri | undefined;
  private studentId = "";

  constructor(private readonly context: vscode.ExtensionContext) {
    this.statusBar.command = "labAssistant.showPanel";
    this.updateStatusBar();
    this.statusBar.show();
  }

  get currentState(): PanelState {
    return this.state;
  }

  private get config() {
    return vscode.workspace.getConfiguration("labAssistant");
  }

  private get api(): ApiClient {
    return new ApiClient(this.config.get<string>("backendUrl", "http://127.0.0.1:8000"));
  }

  async check(options: CheckOptions = {}): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.selection.isEmpty) {
      vscode.window.showInformationMessage("Highlight the code you want to check first.");
      return;
    }
    if (!(await this.ensureConsent())) {
      return;
    }
    const explanation =
      options.explanation ??
      (await vscode.window.showInputBox({
        title: "Lab Assistant: Check my understanding",
        prompt: "Optional: briefly explain what this code is meant to do (press Enter to skip)",
        ignoreFocusOut: true,
      }));
    if (explanation === undefined) {
      return; // Escape cancels the check
    }

    const document = editor.document;
    const root = await this.findRoot(document.uri);
    if (!root) {
      vscode.window.showErrorMessage("Lab Assistant only works on files inside an open folder.");
      return;
    }
    this.projectRoot = root;
    this.studentId = this.config.get<string>("studentId", "");
    const selectedPath = relativePath(root, document.uri);
    const { start, end } = selectedLines(editor.selection);

    this.setState({ ...initialPanelState(), status: "loading", message: "Checking your understanding. This can take a minute..." });
    this.showPanel();

    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Lab Assistant: checking your understanding..." },
      async () => {
        try {
          const candidates = await this.readProject(root);
          const limits = {
            maxFileBytes: this.config.get<number>("maxFileBytes", 200_000),
            maxProjectBytes: this.config.get<number>("maxProjectBytes", 2_000_000),
          };
          const { files } = collectFiles(candidates, selectedPath, document.getText(), limits);
          const response = await this.api.startCheck({
            files,
            selected_path: selectedPath,
            selection: { start, end },
            explanation: explanation.trim() || undefined,
            student_id: this.studentId || undefined,
            skip_questioning: this.config.get<boolean>("skipQuestioning", false),
          });
          const materials: Record<number, MaterialWithImage[]> = {};
          for (const gap of response.session.gaps.filter((g) => g.status === "shown")) {
            materials[gap.index] = await this.withThumbnails(await this.api.materials(response.session.session_id, gap.index));
          }
          this.setState({
            status: "ready",
            session: response.session,
            nextQuestion: response.next_question,
            materials,
            answers: {},
            answering: false,
          });
        } catch (error) {
          this.fail(error);
        }
      },
    );
  }

  showPanel(): void {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside, true);
      return;
    }
    this.panel = vscode.window.createWebviewPanel("labAssistant", "Lab Assistant", { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true }, {
      enableScripts: true,
      localResourceRoots: [], // the panel loads nothing from disk
    });
    this.panel.onDidDispose(() => (this.panel = undefined), null, this.context.subscriptions);
    this.panel.webview.onDidReceiveMessage((message) => this.onMessage(message), null, this.context.subscriptions);
    this.render();
  }

  private async onMessage(message: { type?: string; gapIndex?: number; answer?: string; url?: string; path?: string; line?: number }): Promise<void> {
    if (message.type === "openUrl" && typeof message.url === "string" && isSafeExternalUrl(message.url)) {
      await vscode.env.openExternal(vscode.Uri.parse(message.url));
    } else if (message.type === "reveal" && typeof message.path === "string" && typeof message.line === "number") {
      await this.reveal(message.path, message.line);
    } else if (message.type === "answer" && typeof message.gapIndex === "number" && typeof message.answer === "string") {
      await this.answer(message.gapIndex, message.answer);
    }
  }

  async answer(gapIndex: number, answer: string): Promise<void> {
    const session = this.state.session;
    if (!session || this.state.answering) {
      return;
    }
    this.setState({ ...this.state, answering: true, answers: { ...this.state.answers, [gapIndex]: answer } });
    try {
      const result = await this.api.submitAnswer(session.session_id, gapIndex, answer);
      const refreshed = await this.api.getCheck(session.session_id);
      this.setState({
        ...this.state,
        status: "ready",
        answering: false,
        session: refreshed.session,
        nextQuestion: result.next_question,
        lastChange: result.mastery_change,
        materials: { ...this.state.materials, [gapIndex]: await this.withThumbnails(result.materials) },
      });
    } catch (error) {
      const answers = { ...this.state.answers };
      delete answers[gapIndex]; // let the student try again with their text
      this.setState({ ...this.state, answering: false, answers });
      vscode.window.showErrorMessage(error instanceof ApiError ? error.message : String(error));
    }
  }

  private async ensureConsent(): Promise<boolean> {
    if (this.context.globalState.get<boolean>(CONSENT_KEY)) {
      return true;
    }
    const choice = await vscode.window.showWarningMessage(
      "Lab Assistant sends your selected code and the files in its project folder to the Lab Assistant backend on this computer, which sends them to an external AI service (as configured on the backend) to check your understanding. It never writes solutions. Continue?",
      { modal: true },
      "Send code",
    );
    if (choice === "Send code") {
      await this.context.globalState.update(CONSENT_KEY, true);
      return true;
    }
    return false;
  }

  private async findRoot(uri: vscode.Uri): Promise<vscode.Uri | undefined> {
    const folder = vscode.workspace.getWorkspaceFolder(uri);
    if (!folder) {
      return undefined;
    }
    const fileDir = relativePath(folder.uri, uri).split("/").slice(0, -1);
    const existing = new Set<string>();
    for (let depth = fileDir.length; depth >= 0; depth--) {
      for (const marker of PROJECT_MARKERS) {
        const candidate = vscode.Uri.joinPath(folder.uri, ...fileDir.slice(0, depth), marker);
        try {
          await vscode.workspace.fs.stat(candidate);
          existing.add(fileDir.slice(0, depth).join("/"));
        } catch {
          // marker not present at this level
        }
      }
    }
    const rootSegments = findProjectRoot(fileDir, (dir) => existing.has(dir.join("/")));
    return vscode.Uri.joinPath(folder.uri, ...rootSegments);
  }

  private async readProject(root: vscode.Uri): Promise<CandidateFile[]> {
    const exclude = `**/{${[...IGNORED_DIRS].join(",")}}/**`;
    const uris = await vscode.workspace.findFiles(new vscode.RelativePattern(root, "**/*"), exclude, MAX_FILES);
    const maxFileBytes = this.config.get<number>("maxFileBytes", 200_000);
    const candidates: CandidateFile[] = [];
    for (const uri of uris) {
      const stat = await vscode.workspace.fs.stat(uri);
      // Oversized files are not read at all; collectFiles skips them by size.
      const bytes = stat.size > maxFileBytes ? null : await vscode.workspace.fs.readFile(uri);
      candidates.push({ path: relativePath(root, uri), size: stat.size, bytes });
    }
    return candidates;
  }

  private async withThumbnails(materials: Material[]): Promise<MaterialWithImage[]> {
    return Promise.all(
      materials.map(async (m) => ({ ...m, thumbnailDataUri: m.thumbnail_url ? await this.api.thumbnailDataUri(m.thumbnail_url) : null })),
    );
  }

  /** Jump to a line in the project. Paths come from the webview, so stay inside the project root. */
  private async reveal(path: string, line: number): Promise<void> {
    const root = this.projectRoot;
    if (!root || path.split("/").some((part) => part === ".." || part === "") || !Number.isInteger(line) || line < 1) {
      return;
    }
    const document = await vscode.workspace.openTextDocument(vscode.Uri.joinPath(root, ...path.split("/")));
    const position = new vscode.Position(Math.min(line, document.lineCount) - 1, 0);
    await vscode.window.showTextDocument(document, {
      viewColumn: vscode.ViewColumn.One,
      selection: new vscode.Selection(position, position),
    });
  }

  private fail(error: unknown): void {
    const message = error instanceof ApiError ? error.message : `Unexpected error: ${String(error)}`;
    this.setState({ ...initialPanelState(), status: "error", message });
    vscode.window.showErrorMessage(message);
  }

  private setState(state: PanelState): void {
    this.state = state;
    this.updateDiagnostics();
    this.updateStatusBar();
    this.render();
  }

  private updateStatusBar(): void {
    const { status, answering, session, nextQuestion } = this.state;
    if (status === "loading" || answering) {
      this.statusBar.text = "$(sync~spin) Lab Assistant: checking...";
    } else if (status === "error") {
      this.statusBar.text = "$(error) Lab Assistant";
    } else if (session && nextQuestion) {
      this.statusBar.text = "$(comment-discussion) Lab Assistant: question waiting";
    } else {
      this.statusBar.text = "$(mortar-board) Lab Assistant";
    }
    this.statusBar.tooltip = "Show the Lab Assistant panel";
  }

  private render(): void {
    if (this.panel) {
      this.panel.webview.html = renderPanel(this.state, crypto.randomBytes(16).toString("base64"));
    }
  }

  private updateDiagnostics(): void {
    this.diagnostics.clear();
    const root = this.projectRoot;
    if (!root || !this.state.session) {
      return;
    }
    const byFile = new Map<string, vscode.Diagnostic[]>();
    for (const spec of diagnosticsFor(this.state.session)) {
      const range = new vscode.Range(spec.startLine - 1, 0, spec.endLine - 1, Number.MAX_SAFE_INTEGER);
      // Gaps get a warning underline; quality notes are subtle hints so they don't cover the code in squiggles.
      const severity = spec.kind === "concept-gap" ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Hint;
      const diagnostic = new vscode.Diagnostic(range, spec.message, severity);
      diagnostic.source = "Lab Assistant";
      diagnostic.code = spec.kind;
      byFile.set(spec.path, [...(byFile.get(spec.path) ?? []), diagnostic]);
    }
    for (const [path, diagnostics] of byFile) {
      this.diagnostics.set(vscode.Uri.joinPath(root, ...path.split("/")), diagnostics);
    }
  }
}

function relativePath(root: vscode.Uri, uri: vscode.Uri): string {
  const rootPath = root.path.endsWith("/") ? root.path : `${root.path}/`;
  return uri.path.startsWith(rootPath) ? uri.path.slice(rootPath.length) : uri.path.replace(/^\/+/, "");
}

/** 1-based inclusive lines. A selection ending at column 0 of a line doesn't include that line. */
function selectedLines(selection: vscode.Selection): { start: number; end: number } {
  const start = selection.start.line + 1;
  let end = selection.end.line + 1;
  if (selection.end.character === 0 && end > start) {
    end -= 1;
  }
  return { start, end };
}
