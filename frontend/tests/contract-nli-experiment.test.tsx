import { render, screen, within } from "@testing-library/react";

import { ContractNliExperiment } from "@/components/contract-nli-experiment";

jest.mock("@/lib/api", () => ({
  getContractNliExperiment: jest.fn(),
  getContractNliExperimentDetail: jest.fn(),
  getContractNliHtmlProcess: jest.fn()
}));

const api = jest.requireMock("@/lib/api") as {
  getContractNliExperiment: jest.Mock;
  getContractNliExperimentDetail: jest.Mock;
  getContractNliHtmlProcess: jest.Mock;
};

const report = {
  dataset: "contract_nli",
  run_id: "dev_all_document_level_official_evidence_schema",
  default_sample_id: "12",
  samples: [
    {
      sample_id: "12",
      document_id: 12,
      filename: "sample.pdf",
      text_chars: 100,
      hypotheses: {}
    },
    {
      sample_id: "507",
      document_id: 507,
      filename: "sample.htm",
      text_chars: 120,
      hypotheses: {}
    }
  ],
  report: {
    summary: {
      agent: {
        choice_accuracy: 0.8,
        evidence_f1: 0.5
      },
      direct: {
        choice_accuracy: 0.7,
        evidence_f1: 0.4
      }
    }
  }
};

const detail = {
  summary: {
    task_id: "contract-nli-12",
    status: "completed",
    stage: "done",
    route: "accept",
    route_reason: null,
    error_message: null,
    has_result: true,
    has_trace: true,
    needs_review: false
  },
  result: {
    task_id: "contract-nli-12",
    status: "completed",
    route: "accept",
    fields: []
  },
  trace: null,
  replay: {
    task_id: "contract-nli-12",
    status: "completed",
    stage: "done",
    documents: [{ document_id: "12", filename: "sample.pdf" }],
    display_html: '<h1 id="p000_b000">Contract</h1><p id="p001_b001">Confidential Information includes financial information.</p>',
    outline_tree: [{ id: "p000_b000", type: "TITLE", text: "Contract", children: [] }],
    broad_plan: null,
    actions: [
      {
        tool_name: "search_elements",
        args: {
          query: "Confidential Information",
          limit: 20,
          reason: "Search for Confidential Information clauses"
        },
        result: {
          query: "Confidential Information",
          limit: 20,
          match_count: 1,
          matches: [
            {
              element_id: "p001_b001",
              snippet: "Confidential Information includes financial information.",
              evidence_ids: ["p001_b001"]
            }
          ]
        }
      }
    ],
    field_states: {},
    audit: { route: "accept", route_reason: "内置 ContractNLI 实验样本" }
  },
  review: null,
  audit: null
};

const htmlProcess = {
  sample_id: "12",
  document_id: "12",
  filename: "sample.htm",
  document_type: "sec-html",
  source_kind: "raw-html",
  raw_html_chars: 120,
  agent_html_chars: 90,
  agent_html: '<h1 id="p000_b000">Contract</h1>\n<p id="p001_b000">Information clause</p>',
  display_html: '<h1 id="p001_b000">OISAIR NDA OCR</h1><p id="p001_b001">OCR Confidential Information clause.</p>',
  raw_html_excerpt: "<HTML><BODY><P>Information clause</P></BODY></HTML>",
  agent_html_excerpt: '<h1 id="p000_b000">Contract</h1>\n<p id="p001_b000">Information clause</p>',
  display_html_excerpt: '<h1 id="p001_b000">OISAIR NDA OCR</h1><p id="p001_b001">OCR Confidential Information clause.</p>',
  raw_element_count: 3,
  agent_element_count: 2,
  ocr_block_count: null,
  query_checks: [
    { query: "Confidential Information", match_count: 0 },
    { query: "Information", match_count: 1 }
  ]
};

beforeEach(() => {
  api.getContractNliExperiment.mockResolvedValue(report);
  api.getContractNliExperimentDetail.mockResolvedValue(detail);
  api.getContractNliHtmlProcess.mockResolvedValue(htmlProcess);
});

it("从 backend 读取 ContractNLI 实验并渲染 search_elements trace", async () => {
  render(<ContractNliExperiment />);

  expect(await screen.findByText("ContractNLI")).toBeInTheDocument();
  expect(screen.getByText("dev_all")).toBeInTheDocument();
  expect(screen.getByText("2 samples")).toBeInTheDocument();
  expect(screen.getByText("sample.pdf")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "507" })).toBeInTheDocument();

  const searchCard = await screen.findByLabelText("search_elements 动作结果");
  expect(within(searchCard).getByText("search_elements")).toBeInTheDocument();
  expect(within(searchCard).getByText("Confidential Information")).toBeInTheDocument();
  expect(await screen.findByLabelText("HTML 输入过程")).toBeInTheDocument();
  expect(screen.getByText("raw 3 elements")).toBeInTheDocument();
  expect(screen.getByText("agent 2 elements")).toBeInTheDocument();
  expect(screen.getByText("Information: 1")).toBeInTheDocument();
  expect(api.getContractNliExperimentDetail).toHaveBeenCalledWith("12");
  expect(api.getContractNliHtmlProcess).toHaveBeenCalledWith("12");
});

it("PDF OCR 样本把 OCR HTML 传给 replay 文档视图", async () => {
  render(<ContractNliExperiment />);

  const iframe = (await screen.findByTitle("document replay")) as HTMLIFrameElement;
  expect(iframe.srcdoc).toContain("OISAIR NDA OCR");
  expect(iframe.srcdoc).not.toContain("Confidential Information includes financial information.");
  expect(await screen.findByRole("button", { name: /OCR Confidential Information cl/ })).toBeInTheDocument();
});
