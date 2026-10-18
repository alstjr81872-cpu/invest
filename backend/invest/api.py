import asyncio
import json
import uuid
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Depends, Request, Response, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from .config import settings, validate_web_config
from .db import transaction, utcnow
from .models import Instrument, Dataset, Recommendation, Order, Job, Event, Position
from .auth import require_owner, login, check_origin, COOKIE_NAME, authenticate
from .service import (
    bootstrap,
    portfolio,
    preferences,
    create_research,
    order_dict,
    system_status,
    enqueue_analysis,
    instrument_dict,
)
from .orders import submit, cancel, OrderRejected
from .providers.kis import KISBroker
from . import free_tier


@asynccontextmanager
async def lifespan(app):
    validate_web_config(settings())
    with transaction() as db:
        bootstrap(db)
    yield


app = FastAPI(title="Shortlist", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)


@app.middleware("http")
async def security_headers(request, call_next):
    if settings().free_tier and request.url.path.startswith("/api/"):
        try:
            if request.url.path != "/api/login" and not request.cookies.get(COOKIE_NAME):
                raise HTTPException(401, "로그인이 필요합니다.")
            if request.method not in {"GET", "HEAD"}:
                check_origin(request.headers.get("origin"))
            await asyncio.to_thread(free_tier.reserve, request.url.path, request.method)
            if request.method in {"POST", "PUT"} and request.url.path != "/api/logout":
                await asyncio.to_thread(free_tier.storage_guard)
        except HTTPException as exc:
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers={"Cache-Control": "no-store", **(exc.headers or {})},
            )
        except SQLAlchemyError:
            return JSONResponse(
                {"detail": "DB 사용량 보호를 확인할 수 없어 요청을 중단했습니다."}, status_code=503
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(
        {"detail": "데이터베이스 연결을 확인 중입니다. 주문을 반복하지 말고 상태를 확인하세요."},
        status_code=503,
    )


@app.exception_handler(OrderRejected)
async def order_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(RequestValidationError)
async def invalid_input(request, exc):
    # Pydantic's default error body can echo a submitted password. Never return input values.
    return JSONResponse(
        {
            "detail": "입력값을 확인하세요.",
            "fields": [".".join(str(v) for v in e["loc"]) for e in exc.errors()],
        },
        status_code=422,
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class LoginInput(StrictModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@app.get("/healthz")
def health():
    # Render health checks must not wake a sleeping Neon database.
    if settings().free_tier:
        return {"status": "ok", "database": "checked-on-owner-request"}
    with transaction() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/login")
def login_route(data: LoginInput, request: Request, response: Response):
    check_origin(request.headers.get("origin"))
    token, csrf = login(data.username, data.password, request.client.host if request.client else "unknown")
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=8 * 3600,
        secure=settings().secure_cookie,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return {"csrf": csrf, "username": settings().owner}


@app.get("/api/session")
def current_session(session=Depends(require_owner)):
    return {"csrf": session["csrf"], "username": settings().owner, "expires_at": session["expires_at"]}


@app.post("/api/logout")
def logout(response: Response, session=Depends(require_owner)):
    from .models import AuthSession

    with transaction() as db:
        db.get(AuthSession, session["token_hash"]).revoked = True
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/status", dependencies=[Depends(require_owner)])
def status():
    with transaction() as db:
        return system_status(db)


@app.get("/api/portfolio", dependencies=[Depends(require_owner)])
def get_portfolio():
    with transaction(isolation="REPEATABLE READ") as db:
        return portfolio(db)


@app.get("/api/settings", dependencies=[Depends(require_owner)])
def get_preferences():
    with transaction() as db:
        return preferences(db)


class ExistingHolding(StrictModel):
    instrument_id: str = Field(max_length=64)
    quantity: int = Field(gt=0, le=100000)


class PreferencesInput(StrictModel):
    holding_days: int = Field(ge=2, le=20)
    target_pct: float = Field(gt=0, le=100)
    budget: float = Field(gt=0, le=1000000000)
    currency: Literal["USD", "KRW"]
    loss_budget_usd: float = Field(gt=0, le=1000000)
    max_weight: float = Field(gt=0, le=1)
    max_positions: int = Field(ge=1, le=20)
    existing_holdings: list[ExistingHolding] = Field(default_factory=list, max_length=20)


@app.put("/api/settings", dependencies=[Depends(require_owner)])
def save_preferences(data: PreferencesInput):
    from .orders import lock_account

    with transaction() as db:
        ids = [p.instrument_id for p in data.existing_holdings]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "외부 보유 종목은 종목별로 합산해 입력하세요.")
        for p in data.existing_holdings:
            if not db.get(Instrument, p.instrument_id):
                raise HTTPException(422, "종목 마스터에 없는 보유 종목입니다.")
        account = lock_account(db)
        account.settings = data.model_dump()
        account.version += 1
        return preferences(db)


@app.post("/api/research", dependencies=[Depends(require_owner)])
def research():
    if settings().free_tier:
        free_tier.refresh()
    with transaction(isolation="REPEATABLE READ") as db:
        return create_research(db)


@app.get("/api/research/latest", dependencies=[Depends(require_owner)])
def latest_research():
    with transaction() as db:
        r = db.scalar(select(Recommendation).order_by(Recommendation.created_at.desc()).limit(1))
        return (
            {
                "id": r.id,
                "expires_at": r.expires_at.isoformat(),
                **{k: v for k, v in r.payload.items() if k != "input_snapshot"},
            }
            if r
            else None
        )


@app.get("/api/instruments", dependencies=[Depends(require_owner)])
def instruments():
    with transaction() as db:
        return [
            instrument_dict(i)
            for i in db.scalars(select(Instrument).where(Instrument.kind == "common_stock"))
        ]


@app.get("/api/chart/{instrument_id}", dependencies=[Depends(require_owner)])
def chart(instrument_id: str):
    from .analysis.indicators import indicators
    import pandas as pd

    with transaction() as db:
        ds = db.get(Dataset, instrument_id)
        if not ds or (settings().data_mode != "demo" and ds.metadata_.get("demo")):
            raise HTTPException(409, "검증된 일봉 데이터가 없습니다.")
        frame = indicators(pd.DataFrame(ds.bars))
        # NaN warm-up samples are JSON nulls, never fabricated values.
        rows = json.loads(frame.tail(100).to_json(orient="records"))
        return {"bars": rows, "metadata": ds.metadata_, "period": "완성 일봉", "minute_bars": False}


class OrderInput(StrictModel):
    instrument_id: str = Field(max_length=64)
    side: Literal["buy", "sell"]
    mode: Literal["demo-paper", "live-order"]
    quantity: int = Field(gt=0, le=100000)
    limit_price: float = Field(gt=0, le=1000000)
    displayed_price: float = Field(gt=0, le=1000000)
    tolerance_pct: float = Field(default=0.5, ge=0, le=0.5)
    research_id: str | None = None
    order_type: Literal["limit"] = "limit"
    session: Literal["regular"] = "regular"


@app.post("/api/orders", dependencies=[Depends(require_owner)])
def post_order(data: OrderInput, request: Request):
    key = request.headers.get("idempotency-key", "")
    try:
        uuid.UUID(key)
    except ValueError:
        raise HTTPException(422, "Idempotency-Key UUID가 필요합니다.") from None
    with transaction() as db:
        return order_dict(submit(db, data.model_dump(), key))


@app.get("/api/orders", dependencies=[Depends(require_owner)])
def orders():
    with transaction() as db:
        return [order_dict(o) for o in db.scalars(select(Order).order_by(Order.created_at.desc()).limit(200))]


@app.post("/api/orders/{order_id}/cancel", dependencies=[Depends(require_owner)])
def cancel_order(order_id: str):
    with transaction() as db:
        return order_dict(cancel(db, order_id))


class AnalysisInput(StrictModel):
    instrument_id: str | None = Field(default=None, max_length=64)


@app.post("/api/analysis", dependencies=[Depends(require_owner)])
def analysis(data: AnalysisInput):
    if settings().free_tier:
        free_tier.refresh()
    with transaction() as db:
        try:
            ids = enqueue_analysis(db, data.instrument_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    if settings().free_tier:
        free_tier.complete_jobs(20)
    return {"jobs": ids}


class BacktestInput(StrictModel):
    instrument_id: str = Field(max_length=64)
    holding_days: int = Field(ge=2, le=20)


@app.post("/api/backtest", dependencies=[Depends(require_owner)])
def backtest(data: BacktestInput):
    if settings().data_mode != "demo":
        raise HTTPException(409, "검증된 장기 실데이터가 없습니다.")
    with transaction() as db:
        if not db.get(Instrument, data.instrument_id):
            raise HTTPException(404, "종목 없음")
        key = f"backtest:{data.instrument_id}:{data.holding_days}:{int(utcnow().timestamp()) // 60}"
        job = db.scalar(select(Job).where(Job.dedup_key == key))
        if not job:
            from sqlalchemy.dialects.postgresql import insert

            db.execute(
                insert(Job)
                .values(
                    id=str(uuid.uuid4()),
                    dedup_key=key,
                    kind="backtest",
                    state="queued",
                    payload=data.model_dump(),
                    attempts=0,
                )
                .on_conflict_do_nothing(index_elements=[Job.dedup_key])
            )
            job = db.scalar(select(Job).where(Job.dedup_key == key))
        job_id = job.id
    if settings().free_tier:
        free_tier.complete_jobs(20)
    return {"job_id": job_id}


def job_dict(db, job):
    result = dict(job.result or {}) if job.result else None
    if result and job.kind == "analysis" and job.state == "completed":
        from .models import Quote

        q = db.get(Quote, job.payload["instrument_id"])
        price = result.get("snapshot", {}).get("last")
        pos = db.get(Position, job.payload["instrument_id"])
        result["stale"] = (
            result.get("stale", False)
            or not pos
            or pos.version != result.get("position_version")
            or utcnow() > datetime.fromisoformat(result["valid_until"])
            or (q is not None and price and abs(float(q.last) / price - 1) > 0.01)
        )
    return {
        "id": job.id,
        "kind": job.kind,
        "state": job.state,
        "payload": job.payload,
        "result": result,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@app.get("/api/jobs", dependencies=[Depends(require_owner)])
def jobs():
    with transaction() as db:
        return [job_dict(db, j) for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(100))]


@app.get("/api/history", dependencies=[Depends(require_owner)])
def history():
    with transaction() as db:
        return [
            {"id": e.id, "at": e.at.isoformat(), "kind": e.kind, "payload": e.payload}
            for e in db.scalars(select(Event).order_by(Event.id.desc()).limit(200))
        ]


@app.get("/api/broker/capabilities", dependencies=[Depends(require_owner)])
def broker_capabilities():
    return KISBroker.capabilities


@app.get("/api/dashboard", dependencies=[Depends(require_owner)])
def dashboard():
    """One browser request instead of seven initial reads; no periodic refresh."""
    return {
        "status": status(),
        "portfolio": get_portfolio(),
        "settings": get_preferences(),
        "research": latest_research(),
        "orders": orders(),
        "jobs": jobs(),
        "events": history(),
    }


@app.post("/api/refresh", dependencies=[Depends(require_owner)])
def manual_refresh():
    if not settings().free_tier:
        raise HTTPException(409, "현재는 별도 워커가 갱신합니다.")
    free_tier.refresh()
    free_tier.complete_jobs(2)
    return dashboard()


def stream_snapshot(after):
    with transaction(isolation="REPEATABLE READ") as db:
        events = list(db.scalars(select(Event).where(Event.id > after).order_by(Event.id).limit(100)))
        return {
            "type": "snapshot",
            "portfolio": portfolio(db),
            "status": system_status(db),
            "cursor": events[-1].id if events else after,
            "events": [
                {"id": e.id, "kind": e.kind, "at": e.at.isoformat(), "payload": e.payload} for e in events
            ],
        }


@app.websocket("/api/stream")
async def stream(websocket: WebSocket):
    if settings().free_tier:
        await websocket.close(code=1008, reason="무료 모드: 수동 갱신")
        return
    token = websocket.cookies.get(COOKIE_NAME)
    if websocket.headers.get("origin") != settings().origin or not authenticate(token):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        after = max(0, int(websocket.query_params.get("after", "0")))
    except ValueError:
        after = 0
    try:
        while True:
            if not await asyncio.to_thread(authenticate, token):
                await websocket.close(code=1008, reason="로그인 만료")
                return
            try:
                snapshot = await asyncio.to_thread(stream_snapshot, after)
                after = snapshot["cursor"]
                await websocket.send_json(snapshot)
            except SQLAlchemyError:
                await websocket.send_json({"type": "error", "message": "DB 재연결 중 · 새 주문 보류"})
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        return


DIST = Path(os.getenv("STATIC_DIR", str(Path.cwd() / "frontend" / "dist"))).resolve()
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API 경로 없음")
    if not (DIST / "index.html").exists():
        raise HTTPException(503, "프런트엔드 빌드가 필요합니다.")
    return FileResponse(DIST / "index.html")
