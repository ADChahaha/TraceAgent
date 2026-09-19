import io
import zipfile

from fastapi.testclient import TestClient
from backend.core.config import BackendSettings
from backend.main import create_app
from backend.tests.test_qa_task_flow import AutoAgent
from backend.tests.test_session_manager import FakeStore


def test_full_document_returns_ordered_blocks_of_only_selected_document(tmp_path):
    store = FakeStore()
    app = create_app(settings=BackendSettings(database_path=tmp_path / "full.sqlite3"),
                     agent_client=AutoAgent(object_store=store), object_store=store)
    with TestClient(app) as client:
        session_id = client.post("/chat/sessions").json()["session_id"]
        client.post(f"/chat/sessions/{session_id}/files", files={"files": ("contract.docx", b"doc")})
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("documents/001-contract/010-End/001-last.md", "Last paragraph")
            archive.writestr("documents/002-other/001-first.md", "Other document")
            archive.writestr("documents/001-contract/002-Terms/001-budget.md", "**Budget:** 48,000")
            archive.writestr("documents/001-contract/001-intro.md", "Introduction")
        store.put_object(f"res_{session_id}", "documents.zip", buffer.getvalue())
        url = f"/chat/sessions/{session_id}/documents/full"
        response = client.get(url, params={"key": "documents/001-contract/002-Terms/001-budget.md"})
        assert response.status_code == 200
        result = response.json()
        assert result["key"] == "documents/001-contract"
        assert [block["text"] for block in result["blocks"]] == ["Introduction", "**Budget:** 48,000", "Last paragraph"]
        assert client.get(url, params={"key": "documents/001-contract"}).json() == result
        assert client.get(url, params={"key": "documents/missing"}).status_code == 404
        assert client.get(url, params={"key": "documents/../secret"}).status_code == 422
        other = client.post("/chat/sessions").json()["session_id"]
        assert client.get(f"/chat/sessions/{other}/documents/full", params={"key": result["key"]}).status_code == 404
