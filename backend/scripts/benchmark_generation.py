"""Live latency probe with production services and an isolated in-memory DB.

Run from backend: python -m scripts.benchmark_generation --live
Makes paid API calls; never connects to the configured application database.
Reports timings and token counts, never credentials or generated content.
"""

import argparse
import asyncio
import datetime as dt
import json
import logging
import time
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.content.media import MediaService
from app.content.schemas import GenerateContentRequest
from app.content.service import ContentGenerationService
from app.db import models  # noqa: F401
from app.db.base import Base
from app.llm.client import OpenAILLMClient


async def main(args):
    settings = Settings(
        app_env="local", database_url="sqlite+aiosqlite://",
        llm_mock=False, llm_provider="openai", publish_mock=True,
    )
    report = {
        "timestamp_utc": dt.datetime.now(dt.UTC).isoformat(),
        "scope": "local backend services, real OpenAI, in-memory SQLite; no hosting/browser",
        "settings": {key: getattr(settings, key) for key in (
            "openai_model", "openai_reasoning_effort", "llm_timeout_seconds",
            "llm_max_attempts", "llm_max_concurrency", "generation_deadline_seconds",
            "image_model", "image_quality", "image_size", "image_timeout_seconds",
        )},
        "cases": [],
    }
    print(json.dumps(report["settings"]), flush=True)
    current = {}
    from openai import AsyncOpenAI
    original_init = AsyncOpenAI.__init__
    clients = []

    def instrumented_init(client, *a, **kw):
        original_init(client, *a, **kw)
        clients.append(client)
        for resource, kind in ((client.chat.completions, "text"), (client.images, "image")):
            method_name = "create" if kind == "text" else "generate"
            original = getattr(resource, method_name)

            async def measured(*a, _original=original, _kind=kind, **kw):
                started = time.perf_counter()
                record = {"kind": _kind, "start_s": round(started - current["start"], 3)}
                current["calls"].append(record)
                try:
                    result = await _original(*a, **kw)
                    record["status"] = "ok"
                    usage = getattr(result, "usage", None)
                    if usage is not None:
                        record["usage"] = usage.model_dump()
                    record["request_id"] = getattr(result, "_request_id", None)
                    return result
                except BaseException as exc:
                    record["status"] = type(exc).__name__
                    record["http_status"] = getattr(exc, "status_code", None)
                    raise
                finally:
                    record["seconds"] = round(time.perf_counter() - started, 3)
                    print(json.dumps(record), flush=True)

            setattr(resource, method_name, measured)

    async def case(label, operation):
        current.clear()
        current.update(start=time.perf_counter(), calls=[])
        print(f"START {label}", flush=True)
        result = {"label": label, "calls": current["calls"]}
        value = None
        try:
            value = await operation()
            result["status"] = "ok"
        except Exception as exc:
            result["status"] = type(exc).__name__
        result["seconds"] = round(time.perf_counter() - current["start"], 3)
        report["cases"].append(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"END {label}: {result['status']} {result['seconds']} s", flush=True)
        return value

    engine = create_async_engine("sqlite+aiosqlite://")
    AsyncOpenAI.__init__ = instrumented_init
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            actor_id = uuid.uuid4()
            session.add(models.User(
                id=actor_id, email="latency-probe@example.invalid",
                password_hash="unused", display_name="Local latency probe", is_active=True,
            ))
            await session.commit()
            llm = OpenAILLMClient(settings)
            service = ContentGenerationService(session, llm, settings)
            media = MediaService(session, llm, settings)
            first_item = None
            for effort in args.efforts:
                request = GenerateContentRequest(
                    topic="How adult learning helps people build confidence and practical skills",
                    notes="General community awareness. Do not invent course dates or prices.",
                    platforms=["facebook", "instagram", "linkedin"],
                    reasoning_effort=effort,
                )
                value = await case(f"9 posts / {effort}", lambda request=request: service.generate(
                    request, actor_id=actor_id,
                ))
                if value and first_item is None:
                    first_item = value[1][0].id
                if value is None:
                    await session.rollback()
            if first_item is not None:
                suggestions = await case("image prompt suggestions", lambda: media.suggest_prompts(
                    first_item,
                ))
                prompt = suggestions[0] if suggestions else (
                    "Editorial photograph of adult learners collaborating around a table "
                    "in a bright community classroom. Natural light, no text or logos."
                )
                for quality in args.qualities:
                    await case(f"image / {quality}", lambda quality=quality: media.generate(
                        first_item, prompt=prompt, actor_id=actor_id, quality=quality,
                    ))
    finally:
        AsyncOpenAI.__init__ = original_init
        for client in clients:
            await client.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Run paid real API calls")
    parser.add_argument("--efforts", nargs="+", choices=["minimal", "low", "medium"],
                        default=["low", "low", "medium"])
    parser.add_argument("--qualities", nargs="*", choices=["low", "medium"],
                        default=["medium", "low"])
    parser.add_argument("--output", type=Path, default=Path("../docs/latency-local.json"))
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to enable real paid API requests")
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(args))
