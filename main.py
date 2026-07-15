from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import get_session

app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/db-check")
async def db_check(session: AsyncSession = Depends(get_session)):
    result = await session.exec(text("select 1"))
    return {"db": result.scalar_one()}

