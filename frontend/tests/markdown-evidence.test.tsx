import { fireEvent, render, screen } from "@testing-library/react";

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
});
