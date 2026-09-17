// Decide which workspace files to send with a check. The backend filters again
// (it cannot trust the client); filtering here keeps requests small and private.

import { GitignoreMatcher, globToRegExp } from "./gitignore";
import { ProjectFile } from "./types";

export const IGNORED_DIRS = new Set([
  ".git", ".hg", ".venv", "venv", "env", "__pycache__", "node_modules",
  ".pytest_cache", ".ruff_cache", ".mypy_cache", ".idea", ".vscode", "dist", "build", "out",
]);

const GENERATED = ["*.pyc", "*.pyo", "*.min.js", "*.map", "*.lock", "package-lock.json", ".DS_Store"].map(globToRegExp);

// Folders that mark the root of a lab or assignment.
export const PROJECT_MARKERS = ["SPEC.md", "ASSIGNMENT.md", "pyproject.toml", "setup.py", ".git"];

export interface Limits {
  maxFileBytes: number;
  maxProjectBytes: number;
}

export interface CandidateFile {
  path: string; // project-relative, "/" separators
  size: number;
  bytes: Uint8Array | null; // null when the file was too large to be worth reading
}

export interface CollectedFiles {
  files: ProjectFile[];
  skipped: { path: string; reason: string }[];
}

export function skipReason(path: string, gitignore: GitignoreMatcher | null): string | null {
  const parts = path.split("/");
  if (parts.slice(0, -1).some((part) => IGNORED_DIRS.has(part) || part.endsWith(".egg-info"))) {
    return "ignored directory";
  }
  if (gitignore?.isIgnored(path)) {
    return "matched .gitignore";
  }
  const name = parts[parts.length - 1];
  if (GENERATED.some((regex) => regex.test(name))) {
    return "generated file";
  }
  return null;
}

export function isBinary(bytes: Uint8Array): boolean {
  // Same heuristic as git: a NUL byte near the start means binary.
  return bytes.subarray(0, 8000).includes(0);
}

/**
 * Filter and decode candidate files. The selected file is always kept (with its
 * current editor text) and never counts against being dropped by the size cap.
 */
export function collectFiles(
  candidates: CandidateFile[],
  selectedPath: string,
  selectedText: string,
  limits: Limits,
): CollectedFiles {
  const gitignoreFile = candidates.find((c) => c.path === ".gitignore");
  const gitignore = gitignoreFile?.bytes ? new GitignoreMatcher(decode(gitignoreFile.bytes)) : null;
  const skipped: CollectedFiles["skipped"] = [];
  const files: ProjectFile[] = [{ path: selectedPath, content: selectedText }];
  let total = byteLength(selectedText);

  const sorted = [...candidates].sort((a, b) => a.path.localeCompare(b.path));
  for (const candidate of sorted) {
    if (candidate.path === selectedPath) {
      continue;
    }
    const reason =
      skipReason(candidate.path, gitignore) ??
      (candidate.size > limits.maxFileBytes || candidate.bytes === null ? `larger than ${limits.maxFileBytes} bytes` : null) ??
      (isBinary(candidate.bytes!) ? "binary file" : null) ??
      (total + candidate.size > limits.maxProjectBytes ? "project size cap" : null);
    if (reason || candidate.bytes === null) {
      skipped.push({ path: candidate.path, reason: reason ?? "not read" });
      continue;
    }
    files.push({ path: candidate.path, content: decode(candidate.bytes) });
    total += candidate.size;
  }
  return { files, skipped };
}

/** The nearest ancestor folder (as a list of path segments) containing a project marker. */
export function findProjectRoot(fileDirSegments: string[], hasMarker: (dirSegments: string[]) => boolean): string[] {
  for (let depth = fileDirSegments.length; depth >= 0; depth--) {
    const dir = fileDirSegments.slice(0, depth);
    if (hasMarker(dir)) {
      return dir;
    }
  }
  return [];
}

function decode(bytes: Uint8Array): string {
  return new TextDecoder("utf-8").decode(bytes);
}

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}
