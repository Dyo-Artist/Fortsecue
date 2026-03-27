"""Event streaming endpoints backed by the shared EventBus."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from logos import app_state

router = APIRouter(prefix="/events", tags=["events"])


@router.websocket("/ws")
async def events_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    stream = app_state.EVENT_BUS.subscribe()
    try:
        async for event in stream:
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        return
    finally:
        await stream.aclose()


@router.get("/sse")
async def events_sse(request: Request) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        stream = app_state.EVENT_BUS.subscribe()
        try:
            async for event in stream:
                if await request.is_disconnected():
                    break
                payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
                yield f"data: {payload}\n\n"
        finally:
            await stream.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
