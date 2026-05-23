import fs from "node:fs";
import path from "node:path";

const SRC_DIR = path.join(process.cwd(), "src");
const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);
const HAN_CHARACTER_PATTERN = /[\p{Script=Han}]/u;

it("前端运行时文案统一使用英文", () => {
  const offenders: string[] = [];

  for (const filePath of listSourceFiles(SRC_DIR)) {
    const sourceWithoutComments = stripComments(fs.readFileSync(filePath, "utf8"));
    if (HAN_CHARACTER_PATTERN.test(sourceWithoutComments)) {
      offenders.push(path.relative(process.cwd(), filePath));
    }
  }

  expect(offenders).toEqual([]);
});

function listSourceFiles(dirPath: string): string[] {
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const entryPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      return listSourceFiles(entryPath);
    }
    return SOURCE_EXTENSIONS.has(path.extname(entry.name)) ? [entryPath] : [];
  });
}

function stripComments(source: string): string {
  let output = "";
  let index = 0;
  let state: "code" | "lineComment" | "blockComment" | "singleQuote" | "doubleQuote" | "template" = "code";

  while (index < source.length) {
    const char = source[index];
    const next = source[index + 1] ?? "";

    if (state === "lineComment") {
      if (char === "\n") {
        output += char;
        state = "code";
      }
      index += 1;
      continue;
    }

    if (state === "blockComment") {
      if (char === "*" && next === "/") {
        state = "code";
        index += 2;
      } else {
        index += 1;
      }
      continue;
    }

    output += char;

    if (state === "singleQuote" || state === "doubleQuote" || state === "template") {
      if (char === "\\") {
        output += next;
        index += 2;
        continue;
      }
      if (
        (state === "singleQuote" && char === "'") ||
        (state === "doubleQuote" && char === '"') ||
        (state === "template" && char === "`")
      ) {
        state = "code";
      }
      index += 1;
      continue;
    }

    if (char === "/" && next === "/") {
      output = output.slice(0, -1);
      state = "lineComment";
      index += 2;
      continue;
    }
    if (char === "/" && next === "*") {
      output = output.slice(0, -1);
      state = "blockComment";
      index += 2;
      continue;
    }
    if (char === "'") {
      state = "singleQuote";
    } else if (char === '"') {
      state = "doubleQuote";
    } else if (char === "`") {
      state = "template";
    }
    index += 1;
  }

  return output;
}
