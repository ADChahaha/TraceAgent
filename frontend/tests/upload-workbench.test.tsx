import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { UploadWorkbench } from "@/components/upload-workbench";
import type { Capabilities, TaskCreated } from "@/lib/types";

const capabilities: Capabilities = {
  supported_file_types: ["pdf", "docx"],
  task_types: [],
  routes: ["accept", "review", "reject"],
  review_decisions: ["approve", "revise_and_approve", "reject"],
  features: {
    trace: true,
    review: true,
    audit: true,
    external_task_spec: true,
    multiple_files: true
  }
};

type CreateTaskFn = (formData: FormData) => Promise<TaskCreated>;

function setup(createTask: CreateTaskFn = jest.fn<CreateTaskFn>()) {
  const onCreated = jest.fn();
  render(
    <UploadWorkbench
      capabilities={capabilities}
      createTask={createTask}
      onCreated={onCreated}
    />
  );
  return { createTask: createTask as jest.MockedFunction<CreateTaskFn>, onCreated };
}

it("默认 task_spec 使用 scripts 里的文明寝室模板", () => {
  setup();

  const taskSpec = JSON.parse((screen.getByLabelText("task_spec JSON") as HTMLTextAreaElement).value);
  expect(taskSpec).toMatchObject({
    task_name: "civilized_dormitory",
    fields: [
      {
        field_name: "document_title",
        display_name: "文档标题",
        type: "string",
        required: true
      },
      {
        field_name: "building_name",
        display_name: "楼栋",
        type: "string",
        required: true
      },
      {
        field_name: "civilized_dormitory_rooms",
        display_name: "文明寝室房间号",
        type: "string",
        required: true,
        cross_field_hints: [
          "只抽取表格里“模范/文明”列明确标注为“文明寝室”的房间号。",
          "多个房间号请按出现顺序输出为中文逗号分隔字符串，例如 212、214、302。"
        ]
      },
      {
        field_name: "civilized_dormitory_count",
        display_name: "文明寝室数量",
        type: "string",
        required: true,
        cross_field_hints: ["数量应与文明寝室房间号列表对应。"]
      }
    ]
  });
});

it("非法 task_spec 会阻止提交并提示 JSON object 错误", async () => {
  const user = userEvent.setup();
  const { createTask } = setup();

  await user.upload(
    screen.getByLabelText("上传文件（可多选）"),
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" })
  );
  await user.clear(screen.getByLabelText("task_spec JSON"));
  fireEvent.change(screen.getByLabelText("task_spec JSON"), {
    target: { value: "{bad json" }
  });
  await user.click(screen.getByRole("button", { name: "创建任务" }));

  expect(await screen.findByText("task_spec 必须是合法 JSON object")).toBeInTheDocument();
  expect(createTask).not.toHaveBeenCalled();
});

it("合法 PDF/DOCX 和 JSON 会构造 backend 需要的 FormData", async () => {
  const user = userEvent.setup();
  const created: TaskCreated = {
    task_id: "task-001",
    status: "waiting_review",
    stage: "review"
  };
  const createTask = jest.fn(async () => created);
  const { onCreated } = setup(createTask);

  const files = [
    new File(["%PDF-1.4 fake"], "sample.pdf", { type: "application/pdf" }),
    new File(["fake docx"], "supplement.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    })
  ];

  await user.upload(screen.getByLabelText("上传文件（可多选）"), files);
  await user.clear(screen.getByLabelText("task_type"));
  await user.type(screen.getByLabelText("task_type"), "civilized_dormitory");
  await user.clear(screen.getByLabelText("metadata JSON"));
  fireEvent.change(screen.getByLabelText("metadata JSON"), {
    target: { value: "{\"source\":\"demo\"}" }
  });
  await user.click(screen.getByRole("button", { name: "创建任务" }));

  await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
  const formData = createTask.mock.calls[0][0];
  expect(formData.get("task_type")).toBe("civilized_dormitory");
  expect(JSON.parse(String(formData.get("task_spec")))).toMatchObject({
    task_name: "civilized_dormitory",
    fields: expect.arrayContaining([
      expect.objectContaining({ field_name: "civilized_dormitory_rooms" }),
      expect.objectContaining({ field_name: "civilized_dormitory_count" })
    ])
  });
  expect(JSON.parse(String(formData.get("metadata")))).toEqual({ source: "demo" });
  expect(formData.getAll("files")).toHaveLength(2);
  expect((formData.getAll("files")[0] as File).name).toBe("sample.pdf");
  expect((formData.getAll("files")[1] as File).name).toBe("supplement.docx");
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
});

it("能力边界会显示支持文件类型和 external task_spec 约束", () => {
  setup();

  expect(screen.getByText("支持文件：pdf / docx")).toBeInTheDocument();
  expect(screen.getByText("task_spec 必须由前端显式提交")).toBeInTheDocument();
  expect(screen.getByText("支持多文件任务")).toBeInTheDocument();
  expect(screen.getByText("multipart 字段：files（可重复）")).toBeInTheDocument();
  expect(screen.getByText("旧版 file 字段仅后端兼容，前端固定提交 files。")).toBeInTheDocument();
});
