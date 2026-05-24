"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownEvidenceProps {
  markdown: string;
  className?: string;
  onOpenEvidence?: (uri: string, label: string) => void;
}

type MarkdownChildrenProps = {
  children?: React.ReactNode;
};

type MarkdownAnchorProps = React.AnchorHTMLAttributes<HTMLAnchorElement> & MarkdownChildrenProps;

export function MarkdownEvidence({ markdown, className, onOpenEvidence }: MarkdownEvidenceProps) {
  return (
    <div className={className ?? "space-y-3 text-sm leading-6 text-foreground"}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents(onOpenEvidence)}
        transformLinkUri={transformMarkdownUrl}
      >
        {normalizeMarkdown(markdown)}
      </ReactMarkdown>
    </div>
  );
}

function markdownComponents(onOpenEvidence?: (uri: string, label: string) => void) {
  return {
    h1: ({ children }: MarkdownChildrenProps) => <h2 className="text-sm font-semibold text-foreground">{children}</h2>,
    h2: ({ children }: MarkdownChildrenProps) => <h3 className="text-sm font-semibold text-foreground">{children}</h3>,
    h3: ({ children }: MarkdownChildrenProps) => <h4 className="text-sm font-semibold text-foreground">{children}</h4>,
    h4: ({ children }: MarkdownChildrenProps) => <h5 className="text-sm font-semibold text-foreground">{children}</h5>,
    h5: ({ children }: MarkdownChildrenProps) => <h6 className="text-sm font-semibold text-foreground">{children}</h6>,
    h6: ({ children }: MarkdownChildrenProps) => <h6 className="text-sm font-semibold text-foreground">{children}</h6>,
    p: ({ children }: MarkdownChildrenProps) => <p className="whitespace-pre-wrap text-muted-foreground">{children}</p>,
    ul: ({ children }: MarkdownChildrenProps) => <ul className="list-disc space-y-1 pl-5 text-muted-foreground">{children}</ul>,
    ol: ({ children }: MarkdownChildrenProps) => <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">{children}</ol>,
    li: ({ children }: MarkdownChildrenProps) => <li className="pl-1">{children}</li>,
    table: ({ children }: MarkdownChildrenProps) => (
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full border-collapse text-left text-xs">{children}</table>
      </div>
    ),
    thead: ({ children }: MarkdownChildrenProps) => <thead className="bg-muted text-muted-foreground">{children}</thead>,
    tr: ({ children }: MarkdownChildrenProps) => <tr className="border-t border-border">{children}</tr>,
    th: ({ children }: MarkdownChildrenProps) => <th className="border-b border-border px-3 py-2 font-medium">{children}</th>,
    td: ({ children }: MarkdownChildrenProps) => <td className="px-3 py-2 align-top text-foreground">{children}</td>,
    pre: ({ children }: MarkdownChildrenProps) => <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs text-foreground">{children}</pre>,
    code: ({ children, className, inline }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) => {
      if (!inline && className) {
        return <code className={className}>{children}</code>;
      }
      return <code className="rounded bg-muted px-1 py-0.5 text-xs text-foreground">{children}</code>;
    },
    a: ({ children, href }: MarkdownAnchorProps) => {
      const safeHref = href ?? "";
      const label = textFromChildren(children);
      if (safeHref.startsWith("evidence://")) {
        return (
          <a
            href={safeHref}
            className="replay-evidence-link"
            onClick={
              onOpenEvidence
                ? (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    onOpenEvidence(safeHref, label);
                  }
                : undefined
            }
          >
            {children}
          </a>
        );
      }
      return (
        <a href={safeHref} className="replay-evidence-link" target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
  };
}

function transformMarkdownUrl(url: string): string {
  const trimmed = url.trim();
  if (trimmed.startsWith("evidence://")) {
    return trimmed;
  }
  return ReactMarkdown.uriTransformer(url);
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
    ...rows.map(formatTableRow),
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

function splitTableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function formatTableRow(cells: string[]): string {
  return `| ${cells.join(" | ")} |`;
}

function textFromChildren(children: React.ReactNode): string {
  if (typeof children === "string" || typeof children === "number") {
    return String(children);
  }
  if (Array.isArray(children)) {
    return children.map(textFromChildren).join("");
  }
  if (React.isValidElement<{ children?: React.ReactNode }>(children)) {
    return textFromChildren(children.props.children);
  }
  return "";
}
