from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os

from app.config import get_settings
from app.api.routes import catches, species, weather, admin, explorer, vessels, tide, leads, auth, preferences, notifications
from app.api.routes import settings as settings_routes
from app.api.routes import predictions, bite_windows, inlets, fleet_intel, pelagic_regions, pelagic_tiles
from app.api.routes import usgs, alerts
from app.middleware.rate_limit import RateLimitMiddleware
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

# Rate limiting middleware (120 req/min per client, skips same-origin + tiles)
app.add_middleware(RateLimitMiddleware)

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
app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(preferences.router, prefix="/api/v1/preferences", tags=["preferences"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(settings_routes.router, prefix="/api/v1", tags=["settings"])
app.include_router(predictions.router, prefix="/api/v1/predictions", tags=["predictions"])
app.include_router(bite_windows.router, prefix="/api/v1/bite-windows", tags=["bite-windows"])
app.include_router(inlets.router, prefix="/api/v1/inlets", tags=["inlets"])
app.include_router(fleet_intel.router, prefix="/api/v1/fleet", tags=["fleet-intel"])
app.include_router(pelagic_regions.router, prefix="/api/v1/regions", tags=["regions"])
app.include_router(pelagic_tiles.router, prefix="/api/v1/tiles/pelagic", tags=["pelagic-tiles"])
app.include_router(usgs.router, prefix="/api/v1/usgs", tags=["usgs"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["alerts"])


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

    # Login page
    @app.get("/login")
    async def serve_login():
        login_path = os.path.join(settings.frontend_dir, "login.html")
        if os.path.exists(login_path):
            return FileResponse(login_path)
        return {"message": "Login page not found."}

    # Test landing page (preview new design)
    @app.get("/landing-test")
    async def serve_landing_test():
        test_path = os.path.join(settings.frontend_dir, "landing-test.html")
        if os.path.exists(test_path):
            return FileResponse(test_path)
        return {"message": "Test landing page not found."}

    # Privacy policy
    @app.get("/privacy")
    async def serve_privacy():
        privacy_path = os.path.join(settings.frontend_dir, "privacy.html")
        if os.path.exists(privacy_path):
            return FileResponse(privacy_path)
        return {"message": "Privacy policy not found."}

    # Contact page
    @app.get("/contact")
    async def serve_contact():
        contact_path = os.path.join(settings.frontend_dir, "contact.html")
        if os.path.exists(contact_path):
            return FileResponse(contact_path)
        return {"message": "Contact page not found."}

    # WMS diagnostic test page (temporary)
    @app.get("/wms-test")
    async def serve_wms_test():
        test_path = os.path.join(settings.frontend_dir, "wms-test.html")
        if os.path.exists(test_path):
            return FileResponse(test_path)
        return {"message": "WMS test page not found."}

    # Inshore fishing map
    @app.get("/map/inshore")
    async def serve_inshore_map():
        path = os.path.join(settings.frontend_dir, "inshore.html")
        if os.path.exists(path):
            return FileResponse(path)
        return {"message": "Inshore map not found."}

    # Map UI design variants
    @app.get("/map{variant}")
    async def serve_map_variant(variant: int):
        if variant < 1 or variant > 5:
            return {"message": "Map variant not found."}
        variant_path = os.path.join(settings.frontend_dir, f"map{variant}", "index.html")
        if os.path.exists(variant_path):
            return FileResponse(variant_path)
        return {"message": f"Map variant {variant} not found."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )
