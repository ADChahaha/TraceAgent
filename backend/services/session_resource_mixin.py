"""会话资源命令与文档读取方法集，供 SessionManager 组合复用。"""

from __future__ import annotations

import uuid

from backend.crud import crud
from backend.services.errors import NotFoundError, ValidationError
from backend.services.session_files import (
    check_upload_quota,
    download_session_file,
    list_session_documents,
    map_raw_sizes,
    read_session_block,
    read_session_document,
    read_session_full_document,
    validate_file_shapes,
)
from backend.services.time_utils import utc_now


class SessionResourceMixin:
    """封装会话内文件上传、删除、资源替换与文档读取通道。"""

    async def upload_files(self, files):
        if not files:
            raise ValidationError("files 不能为空")
        validate_file_shapes(files, self.settings.supported_file_types)
        return await self._ask("upload", files)

    async def remove_file(self, resource_id):
        return await self._ask("remove", resource_id)

    async def replace_resources(self, refs, sizes):
        return await self._ask("replace_resources", refs, sizes)

    async def _handle_upload(self, files):
        check_upload_quota(
            self.resources,
            files,
            max_files=self.settings.upload_max_files,
            max_bytes=self.settings.upload_max_bytes,
        )
        refs = await self.document_client.prepare_resources(session_id=self.session_id, files=files)
        return await self._replace_resources(refs, map_raw_sizes(refs, files))

    async def _handle_remove(self, resource_id):
        row = crud.get_resource(self.database.connect(), resource_id)
        if row is None or row["session_id"] != self.session_id:
            raise NotFoundError("资源不存在")
        if row["type"] != "raw":
            raise ValidationError("只能删除原始文件")
        refs = await self.document_client.prepare_resources(
            session_id=self.session_id,
            files=[],
            remove_raw=[{"type": row["type"], "location": row["location"]}],
        )
        return await self._replace_resources(refs, {})

    async def _handle_replace_resources(self, refs, sizes):
        return await self._replace_resources(refs, sizes)

    async def _replace_resources(self, refs, sizes):
        old_sizes = {row["location"]: row["size_bytes"] for row in self.resources if row["type"] == "raw"}

        def replace(db, events):
            now = utc_now()
            crud.delete_resources(db, self.session_id)
            for ref in refs:
                crud.create_resource(
                    db,
                    resource_id=uuid.uuid4().hex,
                    session_id=self.session_id,
                    resource_type=ref["type"],
                    location=ref["location"],
                    now=now,
                    size_bytes=int(sizes.get(ref["location"], old_sizes.get(ref["location"], 0))),
                )
            events.append({
                "type": "resources.prepared",
                "turn_id": None,
                "payload": {
                    "resources": [
                        {"type": ref["type"], "location": ref["location"]}
                        for ref in refs
                        if ref["type"] != "raw"
                    ]
                },
            })

        await self._transaction(replace, [])
        return self.resources

    async def read_block(self, key):
        return await read_session_block(resources=self.resources, document_client=self.document_client, key=key)

    async def read_document(self, key):
        return await read_session_document(resources=self.resources, document_client=self.document_client, key=key)

    async def download_file(self, resource_id):
        return await download_session_file(
            database=self.database,
            session_id=self.session_id,
            resource_id=resource_id,
            object_store=self.object_store,
        )

    async def list_documents(self):
        return await list_session_documents(resources=self.resources, object_store=self.object_store)

    async def read_full_document(self, key):
        return await read_session_full_document(resources=self.resources, object_store=self.object_store, key=key)
