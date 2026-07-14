# Environment file notes

This repository keeps runtime secrets and environment overrides out of
version control by ignoring `.env`. During local development and testing
you may need to copy `.env.example` to `.env` and adjust values.

Relevant change made locally during troubleshooting:

- `CORS_ORIGINS` in `.env` was updated from a comma-separated string:

```
CORS_ORIGINS=http://localhost:8501,http://localhost:3000
```

to a JSON array string so `pydantic-settings` can parse it without error
when loading from dotenv during test runs:

```
CORS_ORIGINS=["http://localhost:8501","http://localhost:3000"]
```

Rationale: the `Settings` model in `backend/app/core/config.py` expects
`CORS_ORIGINS` to be a list. The model also accepts a comma-separated
string, but the dotenv parser can sometimes pass an empty or unexpected
value; using a JSON array ensures deterministic parsing during CI and
local runs.

Notes:
- `.env` remains ignored; do not commit production secrets.
- If you prefer the comma-separated form, revert `.env` and then run
  tests with `CORS_ORIGINS='["http://localhost:8501","http://localhost:3000"]'`.
