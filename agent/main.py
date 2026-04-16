"""提供 OCR 处理和文档抽取相关 API。"""

from fastapi import FastAPI

from routes import ocr_processor_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Service",
        description="OCR 处理和文档抽取相关 API。",
    )
    app.include_router(ocr_processor_router)
    return app


app = create_app()
