from fastapi import FastAPI, HTTPException

from .graphio.upsert import upsert_interaction

app = FastAPI()
PREVIEW_CACHE: dict[str, str] = {}


@app.post("/commit/{interaction_id}")
async def commit(interaction_id: str) -> dict[str, str]:
    preview = PREVIEW_CACHE.get(interaction_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    upsert_interaction(interaction_id, preview)
    return {"status": "committed"}
