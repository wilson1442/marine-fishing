from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os

from app.config import get_settings
from app.api.routes import catches, species, weather, admin, explorer, vessels, tide
from app.scheduler import init_scheduler, shutdown_scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="Marine Fishing Intelligence Platform",
    description="Interactive marine fishing catch and conditions mapping API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Clear legacy admin_token cookie if present
@app.middleware("http")
async def clear_legacy_admin_token(request: Request, call_next):
    response: Response = await call_next(request)
    if request.cookies.get("admin_token"):
        response.delete_cookie(key="admin_token", path="/api/v1/admin", samesite="strict")
    return response


# API routes
app.include_router(catches.router, prefix="/api/v1/catches", tags=["catches"])
app.include_router(species.router, prefix="/api/v1/species", tags=["species"])
app.include_router(weather.router, prefix="/api/v1/weather", tags=["weather"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(explorer.router, prefix="/api/v1/admin/explorer", tags=["explorer"])
app.include_router(vessels.router, prefix="/api/v1/vessels", tags=["vessels"])
app.include_router(tide.router, prefix="/api/v1/tide", tags=["tide"])


# Health check endpoint
@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "marine-fishing-api"}


# Serve static frontend files
if settings.serve_frontend and os.path.exists(settings.frontend_dir):
    # Mount static files (js, css, images)
    static_js = os.path.join(settings.frontend_dir, "js")
    static_css = os.path.join(settings.frontend_dir, "css")

    if os.path.exists(static_js):
        app.mount("/js", StaticFiles(directory=static_js), name="js")
    if os.path.exists(static_css):
        app.mount("/css", StaticFiles(directory=static_css), name="css")

    static_images = os.path.join(settings.frontend_dir, "images")
    if os.path.exists(static_images):
        app.mount("/images", StaticFiles(directory=static_images), name="images")

    # Landing page at root
    @app.get("/")
    async def serve_landing():
        landing_path = os.path.join(settings.frontend_dir, "landing.html")
        if os.path.exists(landing_path):
            return FileResponse(landing_path)
        return {"message": "Frontend not found. API available at /api/docs"}

    # Map dashboard
    @app.get("/map")
    async def serve_map():
        index_path = os.path.join(settings.frontend_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Map not found. API available at /api/docs"}

    # Admin dashboard
    @app.get("/admin")
    async def serve_admin():
        admin_path = os.path.join(settings.frontend_dir, "admin.html")
        if os.path.exists(admin_path):
            return FileResponse(admin_path)
        return {"message": "Admin dashboard not found. API available at /api/docs"}

    # Data explorer
    @app.get("/explorer")
    async def serve_explorer():
        explorer_path = os.path.join(settings.frontend_dir, "explorer.html")
        if os.path.exists(explorer_path):
            return FileResponse(explorer_path)
        return {"message": "Data explorer not found. API available at /api/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )
