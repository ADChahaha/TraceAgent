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

  it("renders final answer evidence as inline numbered citations after sentences", () => {
    const onOpenEvidence = jest.fn();
    const { container } = render(
      <MarkdownEvidence
        markdown={[
          "第一段可以提前终止，但必须提前通知。[30 天通知](evidence://0001.0001.0001/S001)",
          "",
          "第二段要点是书面通知。[书面通知](evidence://0001.0001.0001/S002)"
        ].join("\n")}
        evidencePlacement="citation"
        onOpenEvidence={onOpenEvidence}
      />
    );

    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]).toHaveTextContent("第一段可以提前终止，但必须提前通知。1");
    expect(paragraphs[1]).toHaveTextContent("第二段要点是书面通知。2");
    expect(container.querySelectorAll(".replay-evidence-footer")).toHaveLength(0);
    expect(within(paragraphs[0]).queryByRole("link", { name: "30 天通知" })).not.toBeInTheDocument();
    expect(within(paragraphs[1]).queryByRole("link", { name: "书面通知" })).not.toBeInTheDocument();

    const firstCitation = within(paragraphs[0]).getByRole("link", { name: "Source 1" });
    const secondCitation = within(paragraphs[1]).getByRole("link", { name: "Source 2" });
    expect(firstCitation).toHaveClass("replay-evidence-citation-marker");
    expect(firstCitation).toHaveTextContent("1");
    expect(firstCitation).toHaveAttribute(
      "href",
      "evidence://0001.0001.0001/S001"
    );
    expect(secondCitation).toHaveTextContent("2");
    expect(secondCitation).toHaveAttribute(
      "href",
      "evidence://0001.0001.0001/S002"
    );

    fireEvent.click(firstCitation);
    expect(onOpenEvidence).toHaveBeenCalledWith("evidence://0001.0001.0001/S001", "Source 1");
  });

  it("strips model-authored trailing sources sections in final citation mode", () => {
    const { container } = render(
      <MarkdownEvidence
        markdown={[
          "可以提前终止，但必须提前通知。[1](evidence://0001.0001.0001/S001)",
          "",
          "Sources",
          "- [1](evidence://0001.0001.0001/S001)"
        ].join("\n")}
        evidencePlacement="citation"
      />
    );

    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs).toHaveLength(1);
    expect(paragraphs[0]).toHaveTextContent("可以提前终止，但必须提前通知。1");
    expect(screen.queryByText("Sources")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".replay-evidence-citation-marker")).toHaveLength(1);
  });

  it("renders each bullet evidence as inline numbered citations", () => {
    const { container } = render(
      <MarkdownEvidence
        markdown={[
          "- 终止条款要求提前通知。[30 天通知](evidence://0001.0001.0001/S001)",
          "- 付款条款要求按月支付。[按月支付](evidence://0001.0001.0002/S001)"
        ].join("\n")}
        evidencePlacement="citation"
      />
    );

    const listItems = container.querySelectorAll("li");
    expect(listItems).toHaveLength(2);
    expect(listItems[0]).toHaveTextContent("终止条款要求提前通知。1");
    expect(within(listItems[0]).queryByRole("link", { name: "30 天通知" })).not.toBeInTheDocument();
    expect(within(listItems[0]).getByRole("link", { name: "Source 1" })).toHaveAttribute(
      "href",
      "evidence://0001.0001.0001/S001"
    );
    expect(listItems[1]).toHaveTextContent("付款条款要求按月支付。2");
    expect(within(listItems[1]).queryByRole("link", { name: "按月支付" })).not.toBeInTheDocument();
    expect(within(listItems[1]).getByRole("link", { name: "Source 2" })).toHaveAttribute(
      "href",
      "evidence://0001.0001.0002/S001"
    );
    expect(container.querySelectorAll(".replay-evidence-footer")).toHaveLength(0);
  });
});
