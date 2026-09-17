// A small subset of .gitignore rules, matching the backend's GitignoreMatcher
// (src/labassistant/context/filtering.py): globs, trailing "/" for directories,
// leading or middle "/" to anchor at the root, and "!" negation (last match wins).

interface Rule {
  regex: RegExp;
  negated: boolean;
  dirOnly: boolean;
  anchored: boolean;
}

export class GitignoreMatcher {
  private readonly rules: Rule[] = [];

  constructor(text: string) {
    for (const raw of text.split(/\r?\n/)) {
      let line = raw.trim();
      if (!line || line.startsWith("#")) {
        continue;
      }
      const negated = line.startsWith("!");
      if (negated) {
        line = line.slice(1);
      }
      const dirOnly = line.endsWith("/");
      line = line.replace(/\/+$/, "");
      const anchored = line.startsWith("/") || line.includes("/");
      line = line.replace(/^\/+/, "");
      this.rules.push({ regex: globToRegExp(line), negated, dirOnly, anchored });
    }
  }

  isIgnored(path: string): boolean {
    let ignored = false;
    for (const rule of this.rules) {
      if (matches(path, rule)) {
        ignored = !rule.negated;
      }
    }
    return ignored;
  }
}

function matches(path: string, rule: Rule): boolean {
  const parts = path.split("/");
  const dirPrefixes = parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
  if (rule.anchored) {
    const candidates = rule.dirOnly ? dirPrefixes : [...dirPrefixes, path];
    return candidates.some((c) => rule.regex.test(c));
  }
  const names = rule.dirOnly ? parts.slice(0, -1) : parts;
  return names.some((name) => rule.regex.test(name));
}

/** Like Python's fnmatch: "*" and "?" also match "/", so behaviour matches the backend. */
export function globToRegExp(glob: string): RegExp {
  let pattern = "";
  for (const char of glob) {
    if (char === "*") {
      pattern += ".*";
    } else if (char === "?") {
      pattern += ".";
    } else {
      pattern += char.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    }
  }
  return new RegExp(`^${pattern}$`);
}
