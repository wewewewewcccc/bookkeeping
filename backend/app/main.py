from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import api, stats
from .config import IMAGE_DIR

app = FastAPI(title="AI 记账助手")

@app.post("/api/access/verify")
async def verify_access(request: Request):
    from .config import ACCESS_CODE
    data = await request.json()
    return JSONResponse({"ok": str(data.get("code", "")) == str(ACCESS_CODE)})


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/stats.html")

Base.metadata.create_all(engine)

app.include_router(api.router)
app.include_router(stats.router)

Path(IMAGE_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGE_DIR), name="images")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
