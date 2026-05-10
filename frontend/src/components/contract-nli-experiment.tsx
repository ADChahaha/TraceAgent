"use client";

import * as React from "react";

import { getContractNliExperiment, getContractNliExperimentDetail, getContractNliHtmlProcess } from "@/lib/api";
import type { ContractNliExperimentSummary, ContractNliHtmlProcess, TaskDetailData } from "@/lib/types";
import { ReplayReview } from "@/components/replay-review";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function ContractNliExperiment() {
  const [report, setReport] = React.useState<ContractNliExperimentSummary | null>(null);
  const [selectedSampleId, setSelectedSampleId] = React.useState<string>("");
  const [detail, setDetail] = React.useState<TaskDetailData | null>(null);
  const [htmlProcess, setHtmlProcess] = React.useState<ContractNliHtmlProcess | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let mounted = true;
    getContractNliExperiment()
      .then((loaded) => {
        if (!mounted) {
          return;
        }
        setReport(loaded);
        const defaultSampleId = loaded.default_sample_id || loaded.samples[0]?.sample_id || "";
        setSelectedSampleId(defaultSampleId);
        return defaultSampleId
          ? Promise.all([
              getContractNliExperimentDetail(defaultSampleId),
              getContractNliHtmlProcess(defaultSampleId).catch(() => null)
            ])
          : null;
      })
      .then((loadedPair) => {
        if (mounted && loadedPair) {
          setDetail(loadedPair[0]);
          setHtmlProcess(loadedPair[1]);
        }
      })
      .catch((loadError) => {
        if (mounted) {
          setError(loadError instanceof Error ? loadError.message : "无法加载 ContractNLI 实验");
        }
      })
      .finally(() => {
        if (mounted) {
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  async function selectSample(sampleId: string) {
    setSelectedSampleId(sampleId);
    setError(null);
    setLoading(true);
    try {
      const [loaded, loadedHtmlProcess] = await Promise.all([
        getContractNliExperimentDetail(sampleId),
        getContractNliHtmlProcess(sampleId).catch(() => null)
      ]);
      setDetail(loaded);
      setHtmlProcess(loadedHtmlProcess);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "无法加载样本");
    } finally {
      setLoading(false);
    }
  }

  if (error) {
    return <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>;
  }

  if (!report || !detail) {
    return <div className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">{loading ? "正在加载 ContractNLI..." : "暂无实验数据。"}</div>;
  }

  const summary = report.report.summary;
  const visibleSamples = getVisibleSamples(report.samples);
  const replayForReview = buildReplayForReview(detail.replay, htmlProcess);

  return (
    <main className="space-y-4">
      <section className="rounded-md border bg-background p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">ContractNLI</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              backend 内置实验数据，直接看 agent trace 是否能被人理解。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">dev_all</Badge>
            <Badge variant="secondary">{report.samples.length} samples</Badge>
            <Badge variant="secondary">Acc {summary.agent?.choice_accuracy?.toFixed(3)}</Badge>
            <Badge variant="secondary">Agent F1 {summary.agent?.evidence_f1?.toFixed(3)}</Badge>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {visibleSamples.map((sample) => (
            <Button
              key={sample.sample_id}
              type="button"
              size="sm"
              variant={sample.sample_id === selectedSampleId ? "default" : "outline"}
              onClick={() => void selectSample(sample.sample_id)}
            >
              {sample.sample_id}
            </Button>
          ))}
        </div>
      </section>
      {htmlProcess ? <HtmlProcessPanel process={htmlProcess} /> : null}
      <ReplayReview replay={replayForReview} finalFields={detail.result?.fields ?? []} />
    </main>
  );
}

function buildReplayForReview(replay: TaskDetailData["replay"], htmlProcess: ContractNliHtmlProcess | null) {
  const displayHtml =
    htmlProcess?.display_html ||
    htmlProcess?.agent_html ||
    htmlProcess?.display_html_excerpt ||
    htmlProcess?.agent_html_excerpt;
  if (!replay || !displayHtml) {
    return replay;
  }
  const outlineTree = deriveOutlineFromHtml(displayHtml, replay.outline_tree ?? []);
  return {
    ...replay,
    display_html: displayHtml,
    outline_tree: outlineTree,
  };
}

function deriveOutlineFromHtml(html: string, fallback: NonNullable<TaskDetailData["replay"]>["outline_tree"]) {
  if (typeof window === "undefined" || typeof window.DOMParser === "undefined") {
    return fallback;
  }
  const doc = new window.DOMParser().parseFromString(html, "text/html");
  const blocks = Array.from(doc.querySelectorAll<HTMLElement>("h1[id], h2[id], h3[id], h4[id], h5[id], h6[id], p[id], li[id], table[id]"));
  const nodes = blocks
    .map((block) => {
      const text = block.textContent?.replace(/\s+/g, " ").trim() || block.id;
      return {
        id: block.id,
        type: getOutlineNodeType(block),
        text,
        children: [],
      };
    })
    .filter((node) => node.id && node.text);
  return nodes.length > 0 ? nodes : fallback;
}

function getOutlineNodeType(block: HTMLElement) {
  const tagName = block.tagName.toLowerCase();
  const dataType = block.dataset.type?.toLowerCase() || "";
  if (/^h[1-6]$/.test(tagName) || dataType.includes("title")) {
    return "TITLE";
  }
  if (tagName === "table" || dataType.includes("table")) {
    return "TABLE";
  }
  return "TEXT";
}

function getVisibleSamples(samples: ContractNliExperimentSummary["samples"]) {
  const visible = new Map<string, ContractNliExperimentSummary["samples"][number]>();
  for (const sample of samples.slice(0, 12)) {
    visible.set(sample.sample_id, sample);
  }
  for (const sample of samples) {
    if (/\.(html?|HTML?)$/.test(sample.filename)) {
      visible.set(sample.sample_id, sample);
    }
  }
  return Array.from(visible.values());
}

function HtmlProcessPanel({ process }: { process: ContractNliHtmlProcess }) {
  return (
    <section className="rounded-md border bg-background p-4 shadow-sm" aria-label="HTML 输入过程">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">HTML 输入过程</h2>
          <p className="mt-1 text-sm text-muted-foreground">{process.filename}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{process.source_kind ?? process.document_type ?? "unknown"}</Badge>
          <Badge variant="secondary">raw {process.raw_element_count} elements</Badge>
          <Badge variant="secondary">agent {process.agent_element_count} elements</Badge>
          {process.ocr_block_count ? <Badge variant="secondary">OCR {process.ocr_block_count} blocks</Badge> : null}
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <CodePreview title={`raw HTML · ${process.raw_html_chars} chars`} value={process.raw_html_excerpt} />
        <CodePreview title={`agent HTML · ${process.agent_html_chars} chars`} value={process.agent_html_excerpt} />
      </div>
      {process.display_html_excerpt ? (
        <div className="mt-3">
          <CodePreview title="display HTML preview" value={process.display_html_excerpt} />
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        {process.query_checks.map((item) => (
          <Badge key={item.query} variant={item.match_count > 0 ? "default" : "outline"}>
            {item.query}: {item.match_count}
          </Badge>
        ))}
      </div>
    </section>
  );
}

function CodePreview({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-md border bg-muted/30">
      <div className="border-b px-3 py-2 text-sm font-medium text-foreground">{title}</div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words p-3 text-xs leading-relaxed text-muted-foreground">
        {value}
      </pre>
    </div>
  );
}
