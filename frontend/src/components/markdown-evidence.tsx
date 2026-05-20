"use client";

import * as React from "react";

interface MarkdownEvidenceProps {
  markdown: string;
  className?: string;
  onOpenEvidence?: (uri: string, label: string) => void;
}

type MarkdownBlock =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; lines: string[] }
  | { type: "unordered-list"; items: string[] }
  | { type: "ordered-list"; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "code"; code: string };

export function MarkdownEvidence({ markdown, className, onOpenEvidence }: MarkdownEvidenceProps) {
  const blocks = parseMarkdownBlocks(markdown);
  return (
    <div className={className ?? "space-y-3 text-sm leading-6 text-foreground"}>
      {blocks.map((block, index) => renderBlock(block, index, onOpenEvidence))}
    </div>
  );
}

function renderBlock(
  block: MarkdownBlock,
  index: number,
  onOpenEvidence?: (uri: string, label: string) => void
) {
  if (block.type === "heading") {
    const Tag = (`h${Math.min(block.level + 1, 6)}`) as keyof React.JSX.IntrinsicElements;
    return (
      <Tag key={index} className="text-sm font-semibold text-foreground">
        {renderInline(block.text, onOpenEvidence)}
      </Tag>
    );
  }

  if (block.type === "paragraph") {
    return (
      <p key={index} className="whitespace-pre-wrap text-muted-foreground">
        {renderInline(block.lines.join("\n"), onOpenEvidence)}
      </p>
    );
  }

  if (block.type === "unordered-list") {
    return (
      <ul key={index} className="list-disc space-y-1 pl-5 text-muted-foreground">
        {block.items.map((item, itemIndex) => (
          <li key={`${item}-${itemIndex}`}>{renderInline(item, onOpenEvidence)}</li>
        ))}
      </ul>
    );
  }

  if (block.type === "ordered-list") {
    return (
      <ol key={index} className="list-decimal space-y-1 pl-5 text-muted-foreground">
        {block.items.map((item, itemIndex) => (
          <li key={`${item}-${itemIndex}`}>{renderInline(item, onOpenEvidence)}</li>
        ))}
      </ol>
    );
  }

  if (block.type === "table") {
    return (
      <div key={index} className="overflow-x-auto rounded-md border border-border">
        <table className="w-full border-collapse text-left text-xs">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              {block.headers.map((header, headerIndex) => (
                <th key={`${header}-${headerIndex}`} className="border-b border-border px-3 py-2 font-medium">
                  {renderInline(header, onOpenEvidence)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-t border-border">
                {block.headers.map((_header, cellIndex) => (
                  <td key={cellIndex} className="px-3 py-2 align-top text-foreground">
                    {renderInline(row[cellIndex] ?? "", onOpenEvidence)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <pre key={index} className="overflow-x-auto rounded-md bg-muted p-3 text-xs text-foreground">
      <code>{block.code}</code>
    </pre>
  );
}

function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const lines = normalizeMarkdown(markdown).split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.trim().startsWith("```")) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "code", code: codeLines.join("\n") });
      index += index < lines.length ? 1 : 0;
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line.trim());
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2] });
      index += 1;
      continue;
    }

    if (isTableStart(lines, index)) {
      const headers = splitTableCells(lines[index]);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && isTableRow(lines[index])) {
        rows.push(splitTableCells(lines[index]));
        index += 1;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ""));
        index += 1;
      }
      blocks.push({ type: "unordered-list", items });
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push({ type: "ordered-list", items });
      continue;
    }

    const paragraphLines: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,6})\s+(.+)$/.test(lines[index].trim()) &&
      !isTableStart(lines, index) &&
      !/^\s*[-*+]\s+/.test(lines[index]) &&
      !/^\s*\d+\.\s+/.test(lines[index]) &&
      !lines[index].trim().startsWith("```")
    ) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", lines: paragraphLines });
  }

  return blocks;
}

function normalizeMarkdown(markdown: string): string {
  return markdown
    .replace(/\r\n/g, "\n")
    .split("\n")
    .flatMap((line) => expandCompactTableLine(line) ?? [line])
    .join("\n");
}

function expandCompactTableLine(line: string): string[] | null {
  if (!line.includes("|")) {
    return null;
  }

  const separatorMatch = /\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|/.exec(line);
  if (!separatorMatch) {
    return null;
  }

  const headerPart = line.slice(0, separatorMatch.index).trim();
  const separatorPart = separatorMatch[0].trim();
  const bodyPart = line.slice(separatorMatch.index + separatorMatch[0].length);
  const headers = splitTableCells(headerPart);
  const columnCount = headers.length;
  if (columnCount < 2 || splitTableCells(separatorPart).length !== columnCount) {
    return null;
  }

  const rows = splitCompactTableRows(bodyPart, columnCount);
  if (rows.length === 0) {
    return null;
  }

  return [
    formatTableRow(headers),
    formatTableRow(Array.from({ length: columnCount }, () => "---")),
    ...rows.map(formatTableRow)
  ];
}

function splitCompactTableRows(bodyPart: string, columnCount: number): string[][] {
  const cells = bodyPart.split("|").map((cell) => cell.trim());
  const rows: string[][] = [];
  let currentRow: string[] = [];

  for (const cell of cells) {
    if (currentRow.length === columnCount) {
      rows.push(currentRow);
      currentRow = [];
    }
    if (currentRow.length === 0 && cell === "") {
      continue;
    }
    currentRow.push(cell);
  }

  if (currentRow.length === columnCount) {
    rows.push(currentRow);
  }

  return rows;
}

function formatTableRow(cells: string[]): string {
  return `| ${cells.join(" | ")} |`;
}

function isTableStart(lines: string[], index: number): boolean {
  return Boolean(lines[index]?.includes("|") && lines[index + 1] && isTableSeparator(lines[index + 1]));
}

function isTableSeparator(line: string): boolean {
  const cells = splitTableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function isTableRow(line: string): boolean {
  return line.includes("|") && !isTableSeparator(line);
}

function splitTableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderInline(
  text: string,
  onOpenEvidence?: (uri: string, label: string) => void
): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    if (text[cursor] === "\n") {
      nodes.push(<br key={nodes.length} />);
      cursor += 1;
      continue;
    }

    if (text.startsWith("[", cursor)) {
      const linkMatch = /^\[([^\]]+)\]\((evidence:\/\/[^)\s]+)\)/.exec(text.slice(cursor));
      if (linkMatch) {
        const label = linkMatch[1];
        const href = linkMatch[2];
        nodes.push(
          <a
            key={nodes.length}
            href={href}
            className="replay-evidence-link"
            onClick={
              onOpenEvidence
                ? (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    onOpenEvidence(href, label);
                  }
                : undefined
            }
          >
            {label}
          </a>
        );
        cursor += linkMatch[0].length;
        continue;
      }
    }

    if (text.startsWith("`", cursor)) {
      const end = text.indexOf("`", cursor + 1);
      if (end > cursor) {
        nodes.push(
          <code key={nodes.length} className="rounded bg-muted px-1 py-0.5 text-xs text-foreground">
            {text.slice(cursor + 1, end)}
          </code>
        );
        cursor = end + 1;
        continue;
      }
    }

    if (text.startsWith("**", cursor)) {
      const end = text.indexOf("**", cursor + 2);
      if (end > cursor) {
        nodes.push(
          <strong key={nodes.length} className="font-semibold text-foreground">
            {text.slice(cursor + 2, end)}
          </strong>
        );
        cursor = end + 2;
        continue;
      }
    }

    const nextSpecial = findNextSpecial(text, cursor + 1);
    nodes.push(text.slice(cursor, nextSpecial));
    cursor = nextSpecial;
  }

  return nodes;
}

function findNextSpecial(text: string, start: number): number {
  const indexes = ["\n", "[", "`", "**"]
    .map((token) => text.indexOf(token, start))
    .filter((index) => index >= 0);
  return indexes.length > 0 ? Math.min(...indexes) : text.length;
}
