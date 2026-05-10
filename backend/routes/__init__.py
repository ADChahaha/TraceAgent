from backend.routes.capabilities import router as capabilities_router
from backend.routes.experiments import router as experiments_router
from backend.routes.reviews import router as reviews_router
from backend.routes.tasks import router as tasks_router

__all__ = [
    "capabilities_router",
    "experiments_router",
    "reviews_router",
    "tasks_router",
]
