import assert from "node:assert/strict";
import { test } from "node:test";
import { GitignoreMatcher } from "../gitignore";

// Same cases as tests/test_context_models_and_filtering.py, so client and backend agree.
const cases: [string, string, boolean][] = [
  ["*.log", "logs/app.log", true],
  ["secrets/", "secrets/key.txt", true],
  ["secrets/", "secrets", false],
  ["/build.py", "build.py", true],
  ["/build.py", "tools/build.py", false],
  ["docs/*.md", "docs/a.md", true],
  ["docs/*.md", "other/docs/a.md", false],
  ["*.txt\n!keep.txt", "keep.txt", false],
  ["# comment\n\n*.tmp", "x.tmp", true],
  ["a+b.py", "a+b.py", true], // regex characters are literal
];

for (const [patterns, path, ignored] of cases) {
  test(`gitignore ${JSON.stringify(patterns)} on ${path} -> ${ignored}`, () => {
    assert.equal(new GitignoreMatcher(patterns).isIgnored(path), ignored);
  });
}
