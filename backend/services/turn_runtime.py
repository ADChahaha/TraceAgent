"""后台等待 gRPC，把事件逐条交回 manager；取消只操作本轮 call。"""

import asyncio
import uuid


class TurnRuntime:
    def __init__(self, manager, turn_id, files, run_options):
        self.manager = manager
        self.turn_id = turn_id
        self.generation = uuid.uuid4().hex
        self.files = files
        self.run_options = run_options
        self.call = None
        self.cancel_requested = False
        self.task = None
        self.reported = False
        self.cleanup_task = None

    def start(self):
        self.task = asyncio.create_task(self.run(), name=f"turn:{self.turn_id}")
        self.task.add_done_callback(self._ensure_reported)

    def _ensure_reported(self, task):
        if not task.cancelled():
            task.exception()
        if not self.reported:
            self.reported = True
            self.cleanup_task = asyncio.create_task(self.manager.worker_ended(
                self.turn_id, self.generation, "执行在启动前已取消"))

    async def wait_closed(self):
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)
        if self.cleanup_task:
            await self.cleanup_task

    def cancel(self):
        if self.cancel_requested:
            return
        self.cancel_requested = True
        if self.call is not None:
            self.call.cancel()
        if self.task is not None:
            self.task.cancel()

    async def run(self):
        error = None
        try:
            if self.files:
                refs = await self.manager.agent_client.prepare_resources(self.files)
                self.files = []
                await self.manager.resources_prepared(self.turn_id, self.generation, refs)
            request = await self.manager.start_turn(self.turn_id, self.generation)
            if request is None or self.cancel_requested:
                return
            self.call = self.manager.agent_client.chat_completion(**request, run_options=self.run_options)
            if self.cancel_requested:
                self.call.cancel()
                return
            async for event in self.call:
                accepted = await self.manager.agent_event(self.turn_id, self.generation, event)
                if not accepted:
                    break
        except asyncio.CancelledError:
            error = "执行已取消"
        except Exception as exc:
            error = str(exc)
        finally:
            self.files = []
            if self.call is not None:
                self.call.cancel()
            self.reported = True
            await self.manager.worker_ended(self.turn_id, self.generation, error or "agent 未返回终态便结束流")
