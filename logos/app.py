from fastapi import FastAPI

app = FastAPI()


@app.get("/ingest/preview")
def ingest_preview() -> dict[str, str]:
    """Return a simple status payload for preview."""
    return {"status": "ok"}
