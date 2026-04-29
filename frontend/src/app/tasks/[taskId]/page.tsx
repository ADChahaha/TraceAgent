import { TaskDetail } from "@/components/task-detail";

type TaskPageProps = {
  params: Promise<{
    taskId: string;
  }>;
};

export default async function TaskPage({ params }: TaskPageProps) {
  const { taskId } = await params;
  return <TaskDetail taskId={taskId} />;
}
