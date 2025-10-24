# Fortsecue
For Fortescue related diagrams and code

## Dependencies

- fastapi
- httpx
- pytest
- python-multipart
- ruff

## Development

Run `./setup.sh` to install dependencies and run lint/tests. The script hashes
`requirements.txt` (and other dependency files) and caches the installed
packages under `.cache/`. When the hash hasn't changed, the install step is
skipped, speeding up repeated runs.

### Transcription configuration

Audio ingestion uses the OpenAI Whisper API. Configure the following environment
variables before running the application:

- `OPENAI_API_KEY` – required API key used for authenticating with the OpenAI
  API.
- `OPENAI_WHISPER_MODEL` – optional model name for transcription (defaults to
  `whisper-1`).
