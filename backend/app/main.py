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


@app.get("/")
def root():
    return {"service": "influencer-matching", "status": "ok", "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}
