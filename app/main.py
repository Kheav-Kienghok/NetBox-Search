import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import get_meta, init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.search import search_cache
from app.sync import run_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("netbox_search")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    search_cache.reload()

    if settings.sync_on_startup:
        try:
            run_sync()
        except Exception:
            logger.exception(
                "Initial NetBox sync failed - check NETBOX_URL/NETBOX_TOKEN in .env. "
                "The app will keep running and retry on the scheduled interval; "
                "you can also trigger POST /sync manually once fixed."
            )

    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="NetBox Search", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "last_sync_at": get_meta("last_sync_at"),
            "last_sync_count": get_meta("last_sync_count"),
            "index_size": search_cache.size(),
            "sync_interval_hours": settings.sync_interval_hours,
            "results": search_cache.all_rows(),
            "query": "",
        },
    )


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    results = search_cache.search(q)
    return templates.TemplateResponse(
        request, "partials/results.html", {"results": results, "query": q}
    )


@app.post("/sync", response_class=HTMLResponse)
def sync_now(request: Request):
    try:
        count = run_sync()
        message = f"Synced {count} records from NetBox."
        ok = True
    except Exception as exc:
        logger.exception("Manual sync failed")
        message = f"Sync failed: {exc}"
        ok = False

    return templates.TemplateResponse(
        request,
        "partials/sync_status.html",
        {
            "ok": ok,
            "message": message,
            "last_sync_at": get_meta("last_sync_at"),
            "last_sync_count": get_meta("last_sync_count"),
        },
    )
