"""FastAPI app serving fastberry.rest output.

fastberry.rest returns orjson bytes; we hand them straight back as the response
body. No DRF, no FastJSONRenderer — those are Django-only. The only thing the
SQLAlchemy backend needs is a Session, provided here via a dependency.
"""

from fastapi import Depends, FastAPI, HTTPException, Response
from sqlalchemy.orm import Session

from app import schemas
from app.db import SessionLocal
from app.models import House

app = FastAPI(title="fastberry + FastAPI + SQLAlchemy")


def get_session():
    with SessionLocal() as session:
        yield session


def _json(body: bytes) -> Response:
    return Response(content=body, media_type="application/json")


@app.get("/houses")
def houses(session: Session = Depends(get_session)):
    return _json(schemas.HouseRest.serialize_json(session=session))


@app.get("/houses/{house_id}")
def house_detail(house_id: int, session: Session = Depends(get_session)):
    obj = session.get(House, house_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="House not found")
    return _json(schemas.HouseRest.serialize_obj_json(obj, session=session))


@app.get("/stocks")
def stocks(session: Session = Depends(get_session)):
    return _json(schemas.StockRest.serialize_json(session=session))
