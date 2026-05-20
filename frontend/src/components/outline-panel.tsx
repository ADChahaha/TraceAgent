"use client";

import React from "react";
import type { ReplayOutlineNode } from "@/lib/types";

const OUTLINE_ACTIVE_TOP_OFFSET_PX = 96;

interface OutlinePanelProps {
  outlineTree: ReplayOutlineNode[];
  fieldStates?: Record<string, { status?: string; value?: unknown }>;
  activeNodeId: string | null;
  onNodeClick: (nodeId: string, label: string) => void;
  onNodeHover?: (nodeId: string | null) => void;
}

export function OutlinePanel({
  outlineTree,
  fieldStates,
  activeNodeId,
  onNodeClick,
  onNodeHover,
}: OutlinePanelProps) {
  const listRef = React.useRef<HTMLDivElement | null>(null);

  React.useLayoutEffect(() => {
    if (!activeNodeId || !listRef.current) {
      return;
    }
    const activeItem = Array.from(
      listRef.current.querySelectorAll<HTMLElement>("[data-outline-node-id]")
    ).find((item) => item.dataset.outlineNodeId === activeNodeId);
    if (!activeItem) {
      return;
    }
    const nextTop = Math.max(0, activeItem.offsetTop - OUTLINE_ACTIVE_TOP_OFFSET_PX);
    if (typeof listRef.current.scrollTo === "function") {
      listRef.current.scrollTo({ top: nextTop, behavior: "auto" });
    } else {
      listRef.current.scrollTop = nextTop;
    }
  }, [activeNodeId]);

  return (
    <nav className="replay-outline-panel" aria-label="Contents">
      <div className="replay-outline-panel-header">
        <span className="replay-outline-panel-title">Contents</span>
      </div>
      <div ref={listRef} className="replay-outline-panel-list" role="tree">
        {outlineTree.map((node, i) => (
          <OutlineNode
            key={node.id ?? i}
            node={node}
            depth={0}
            activeNodeId={activeNodeId}
            fieldStates={fieldStates}
            onNodeClick={onNodeClick}
            onNodeHover={onNodeHover}
          />
        ))}
      </div>
    </nav>
  );
}

/* --- recursive node --- */

interface OutlineNodeProps {
  node: ReplayOutlineNode;
  depth: number;
  activeNodeId: string | null;
  fieldStates?: Record<string, { status?: string; value?: unknown }>;
  onNodeClick: (nodeId: string, label: string) => void;
  onNodeHover?: (nodeId: string | null) => void;
}

function OutlineNode({
  node,
  depth,
  activeNodeId,
  fieldStates,
  onNodeClick,
  onNodeHover,
}: OutlineNodeProps) {
  const nodeId = node.id ?? "";
  const label = node.label ?? node.text ?? "";
  const isActive = activeNodeId === nodeId;
  const hasChildren = node.children && node.children.length > 0;

  const fieldValue = nodeId ? fieldStates?.[nodeId] : undefined;
  const statusText =
    fieldValue?.status === "resolved" && fieldValue.value != null
      ? String(fieldValue.value)
      : null;

  const className = [
    "replay-outline-item",
    isActive ? "outline-item-active" : "",
    hasChildren ? "replay-outline-item-section" : "replay-outline-item-leaf",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <>
      <div
        className={className}
        style={{ paddingLeft: `${12 + depth * 14}px` }}
        onClick={() => nodeId && onNodeClick(nodeId, label)}
        onMouseEnter={() => onNodeHover?.(nodeId || null)}
        onMouseLeave={() => onNodeHover?.(null)}
        role="treeitem"
        aria-selected={isActive}
        aria-level={depth + 1}
        data-outline-node-id={nodeId || undefined}
      >
        {!hasChildren && <span className="virtual-file-leaf-dot" />}
        <span className="replay-outline-item-label">{label}</span>
        {statusText && (
          <span className="replay-outline-item-value">{statusText}</span>
        )}
      </div>
      {node.children?.map((child, i) => (
        <OutlineNode
          key={child.id ?? i}
          node={child}
          depth={depth + 1}
          activeNodeId={activeNodeId}
          fieldStates={fieldStates}
          onNodeClick={onNodeClick}
          onNodeHover={onNodeHover}
        />
      ))}
    </>
  );
}
