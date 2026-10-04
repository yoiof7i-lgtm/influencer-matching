from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models
from app.database import engine
from app.routers import auth, users, reviews

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Influencer Matching API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 배포 시 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(reviews.router)

# 프론트엔드 정적 서빙 (MVP — /web에서 index.html, /static은 파일 직접)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

FRONTEND_PATH = "/code/frontend"
LOCAL_FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
FRONTEND_PATH = FRONTEND_PATH if os.path.isdir(FRONTEND_PATH) else LOCAL_FRONTEND

if os.path.isdir(FRONTEND_PATH):
    app.mount("/static", StaticFiles(directory=FRONTEND_PATH), name="static")

    @app.get("/web")
    def web():
        # 브라우저(특히 모바일) 캐시 방지 — 항상 최신 HTML 받도록
        resp = FileResponse(os.path.join(FRONTEND_PATH, "index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp


@app.get("/")
def root():
    return {"service": "influencer-matching", "status": "ok", "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}
