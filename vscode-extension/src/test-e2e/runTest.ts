// End-to-end test: launches a real VS Code with the extension against a real backend.
//
//   npm run test:e2e                      scripted LLM backend (repeatable, no API key)
//   E2E_BACKEND_URL=http://127.0.0.1:8000 npm run test:e2e
//                                         an already-running real backend (uses the API)

import { ChildProcess, spawn } from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { runTests } from "@vscode/test-electron";

const EXTENSION_ROOT = path.resolve(__dirname, "../..");
const REPO_ROOT = path.resolve(EXTENSION_ROOT, "..");
const FAKE_PORT = 8799;

function seededProject(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "labassistant-e2e-"));
  fs.cpSync(path.join(REPO_ROOT, "sample_labs", "file_tree"), dir, {
    recursive: true,
    filter: (src) => !src.includes("__pycache__"),
  });
  const metrics = path.join(dir, "metrics.py");
  fs.writeFileSync(metrics, fs.readFileSync(metrics, "utf8").replace("count = 0", "count = 1"));
  return dir;
}

async function waitForHealth(url: string, seconds: number): Promise<void> {
  for (let i = 0; i < seconds * 2; i++) {
    try {
      if ((await fetch(`${url}/health`)).ok) {
        return;
      }
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`backend at ${url} did not start`);
}

async function main(): Promise<void> {
  const project = seededProject();
  let backend: ChildProcess | undefined;
  let backendUrl = process.env.E2E_BACKEND_URL;
  if (!backendUrl) {
    backendUrl = `http://127.0.0.1:${FAKE_PORT}`;
    backend = spawn("uv", ["run", "python", "-m", "tests.e2e.fake_backend", "--port", String(FAKE_PORT), "--project", project], {
      cwd: REPO_ROOT,
      stdio: "inherit",
    });
  }
  try {
    await waitForHealth(backendUrl, 60);
    await runTests({
      extensionDevelopmentPath: EXTENSION_ROOT,
      extensionTestsPath: path.join(__dirname, "suite"),
      launchArgs: [project, "--disable-extensions", "--skip-welcome", "--skip-release-notes"],
      extensionTestsEnv: { E2E_BACKEND_URL: backendUrl, E2E_REAL_LLM: process.env.E2E_BACKEND_URL ? "1" : "" },
    });
  } finally {
    backend?.kill();
    fs.rmSync(project, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
