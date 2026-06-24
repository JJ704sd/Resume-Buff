"""
简历帮 - FastAPI 后端入口

启动: python main.py
       或: uvicorn main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.materials import router as materials_router
from api.resume import router as resume_router

app = FastAPI(
    title="简历帮 API",
    description="个人简历助手 - 素材库 + 简历生成",
    version="0.1.0",
)

# CORS - 开发期放开,生产再收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(materials_router, prefix="/api/materials", tags=["materials"])
app.include_router(resume_router, prefix="/api/resume", tags=["resume"])


@app.get("/")
def root():
    return {"name": "简历帮", "version": "0.1.0", "docs": "/docs"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
