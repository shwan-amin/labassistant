import assert from "node:assert/strict";
import { test } from "node:test";
import { CandidateFile, collectFiles, findProjectRoot } from "../projectFiles";

const encode = (text: string) => new TextEncoder().encode(text);
const file = (path: string, text: string): CandidateFile => ({ path, size: encode(text).length, bytes: encode(text) });
const limits = { maxFileBytes: 100, maxProjectBytes: 1000 };

test("collects files, skips junk, and records reasons", () => {
  const candidates: CandidateFile[] = [
    file("metrics.py", "on disk version"),
    file("tree.py", "class Node: pass"),
    file(".gitignore", "private/\n"),
    file("private/answers.py", "secret"),
    file(".venv/lib/x.py", "x"),
    file("__pycache__/tree.pyc", "x"),
    file("uv.lock", "x"),
    { path: "image.png", size: 4, bytes: new Uint8Array([137, 80, 0, 1]) },
    { path: "big.csv", size: 5000, bytes: null },
  ];
  const result = collectFiles(candidates, "metrics.py", "unsaved editor text", limits);

  assert.deepEqual(result.files.map((f) => f.path), ["metrics.py", ".gitignore", "tree.py"]);
  assert.equal(result.files[0].content, "unsaved editor text"); // the editor's text, not the disk copy
  assert.deepEqual(Object.fromEntries(result.skipped.map((s) => [s.path, s.reason])), {
    ".venv/lib/x.py": "ignored directory",
    "__pycache__/tree.pyc": "ignored directory",
    "big.csv": "larger than 100 bytes",
    "image.png": "binary file",
    "private/answers.py": "matched .gitignore",
    "uv.lock": "generated file",
  });
});

test("project size cap never drops the selected file", () => {
  const result = collectFiles([file("a.py", "a".repeat(60)), file("b.py", "b".repeat(60))], "sel.py", "s".repeat(90), {
    maxFileBytes: 100,
    maxProjectBytes: 160,
  });
  assert.deepEqual(result.files.map((f) => f.path), ["sel.py", "a.py"]);
  assert.equal(result.skipped[0].reason, "project size cap");
});

test("project root is the nearest folder with a marker", () => {
  const markers = new Set(["", "labs/file_tree"]);
  const has = (dir: string[]) => markers.has(dir.join("/"));
  assert.deepEqual(findProjectRoot(["labs", "file_tree", "src"], has), ["labs", "file_tree"]);
  assert.deepEqual(findProjectRoot(["other"], has), []);
  assert.deepEqual(findProjectRoot(["x"], () => false), []);
});
