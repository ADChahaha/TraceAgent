import { fireEvent, render, screen, within } from "@testing-library/react";

import { MarkdownEvidence } from "@/components/markdown-evidence";


describe("MarkdownEvidence", () => {
  it("renders ordered list items with nested bullet details as one list", () => {
    const markdown = [
      "当然。",
      "",
      "1. 马云创办了阿里巴巴。",
      "   - 马云：人名",
      "   - 阿里巴巴：机构名",
      "",
      "2. 苹果公司总部位于美国加利福尼亚州。",
      "   - 苹果公司：机构名",
      "   - 美国：地名",
      "   - 加利福尼亚州：地名",
    ].join("\n");
    const { container } = render(<MarkdownEvidence markdown={markdown} />);

    const orderedLists = container.querySelectorAll("ol");
    const firstItem = screen.getByText("马云创办了阿里巴巴。").closest("li");
    const secondItem = screen.getByText("苹果公司总部位于美国加利福尼亚州。").closest("li");

    expect(orderedLists).toHaveLength(1);
    expect(orderedLists[0].children).toHaveLength(2);
    expect(firstItem?.querySelectorAll("ul > li")).toHaveLength(2);
    expect(secondItem?.querySelectorAll("ul > li")).toHaveLength(3);
  });

  it("keeps evidence links clickable after markdown rendering", () => {
    const onOpenEvidence = jest.fn();
    render(
      <MarkdownEvidence
        markdown={"结论见 [30 天通知](evidence://0001.0001.0001/S001)。"}
        onOpenEvidence={onOpenEvidence}
      />
    );

    fireEvent.click(screen.getByRole("link", { name: "30 天通知" }));

    expect(onOpenEvidence).toHaveBeenCalledWith("evidence://0001.0001.0001/S001", "30 天通知");
  });

  it("moves final answer evidence links into a sources footer", () => {
    const onOpenEvidence = jest.fn();
    const { container } = render(
      <MarkdownEvidence
        markdown={"可以提前终止，但必须提前通知。[30 天通知](evidence://0001.0001.0001/S001)"}
        evidencePlacement="footer"
        onOpenEvidence={onOpenEvidence}
      />
    );

    const paragraph = screen.getByText("可以提前终止，但必须提前通知。30 天通知");
    expect(within(paragraph).queryByRole("link")).not.toBeInTheDocument();
    const sources = screen.getByLabelText("Sources");
    const citation = within(sources).getByRole("link", { name: "Source 1: 30 天通知" });

    expect(citation).toHaveAttribute("href", "evidence://0001.0001.0001/S001");
    expect(container.querySelector(".replay-evidence-footer")).toBeInTheDocument();

    fireEvent.click(citation);

    expect(onOpenEvidence).toHaveBeenCalledWith("evidence://0001.0001.0001/S001", "30 天通知");
  });

  it("renders a model-authored sources section as the unified footer", () => {
    const { container } = render(
      <MarkdownEvidence
        markdown={"可以提前终止，但必须提前通知。\n\nSources\n[1] [30 天通知](evidence://0001.0001.0001/S001)"}
        evidencePlacement="footer"
      />
    );

    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs).toHaveLength(1);
    expect(paragraphs[0]).toHaveTextContent("可以提前终止，但必须提前通知。");
    const sources = screen.getByLabelText("Sources");

    expect(within(sources).getByRole("link", { name: "Source 1: 30 天通知" })).toBeInTheDocument();
  });
});
