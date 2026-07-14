# AITraderPro

An AI-assisted algorithmic trading platform for Indian equity markets (NSE/BSE), built as four independently shippable phases on a single FastAPI + Postgres + Redis foundation.

**Phase 1 (this delivery) is complete and green:** 31 tests passing, lint clean, Docker Compose stack boots end to end.

---

## Target architecture

```
                                    +-----------------------+
                                    |   TradingView Desktop |
                                    |    (Charts & Alerts)  |
                                    +-----------+-----------+
                                                |
                                            MCP Server                  <- Phase 3
                                                |
+-----------------------------------------------------------------------+
|                          Claude Desktop                               |
|    AI Strategy Builder - Pine Script - Trade Explanation              |
+-------------------------------+---------------------------------------+
                                |
                +---------------+---------------+
                |                               |
        Python Trading Engine             AI Agent Orchestrator
                |                               |
    +-----------+-----------+-------------------+-----------------+
    |           |           |                   |                 |
    v           v           v                   v                 v
 Market     Fundamental    News            Risk Manager     Portfolio Manager
 Scanner      Analyzer    Analyzer                                          <- Phase 4
    |           |           |                   |                 |
    +-----------+-----------+-------------------+-----------------+
                                |
                         Decision Engine
                                |
                +---------------+----------------+
                |                                |
         Zerodha Kite API                 Streamlit Dashboard
                |                                |            <- Phase 2
         Order Management                 PostgreSQL Database
```

### Where each phase plugs in

| Layer in the diagram | Phase | Lands in |
| --- | --- | --- |
| PostgreSQL, Streamlit shell, auth, config, logging | **1 — done** | `backend/app/`, `dashboard/` |
| Market Scanner, indicators, Technical Agent | **4a — done** | `backend/app/indicators/`, `scanners/`, `agents/` |
| Zerodha Kite API, Order Management, live ticks | 2 | `backend/app/brokers/kite/` |
| MCP Server, Claude Desktop, Pine Script generation | 3 | `backend/app/mcp/` |
| Risk & Portfolio Manager, Decision Engine | 4b | `backend/app/engine/`, `agents/` |

### The scanner stack is layered, not flat

```
indicators/   pure math          ema(close, 9) -> Series
scanners/     criteria on math   "EMA9 crossed EMA21 on 2.3x volume" -> Signal
agents/       interpretation     "bullish, moderate, but volume disagrees" -> TechnicalView
engine/       decision           entry, stop, size -> Order   (next)
```

Each layer imports only from the layer below. That is what stops EMA from being
implemented three times and disagreeing — see [docs/LAYERING.md](docs/LAYERING.md).

Phase 1 deliberately builds the parts every later phase leans on: identity (who is placing this order), persistence, cache, migrations, config, structured logging, and CI. Nothing above is stubbed with fake abstractions — the extension points are real modules, added when their phase arrives.

---

## Phase 1 — what is actually in the box

- **FastAPI backend**, versioned under `/api/v1`, application-factory pattern, OpenAPI at `/docs`
- **JWT authentication** — access + refresh tokens, refresh-token **rotation** (a replayed refresh token is rejected), logout via a **Redis blocklist**, refresh tokens stored as SHA-256 digests so a database leak cannot mint sessions
- **User management** — registration, profile updates, password change, role-based access (`admin` / `trader` / `viewer`), admin-only listing, privilege-escalation guard on self-update
- **PostgreSQL** via async SQLAlchemy 2.0 + **Alembic** migrations (initial revision `0001` included)
- **Redis** for the token blocklist (and quote caching from Phase 2)
- **Audit log** table — every login, failed login and logout is recorded, ready to carry order events in Phase 2
- **Structured logging** — request-id ContextVar on every log line, JSON mode for production, latency on every request
- **Streamlit dashboard skeleton** — login/register, session handling with silent token refresh, health indicator, settings, placeholder overview
- **Pytest** — 31 tests, 82% coverage, runs against in-memory SQLite with **zero infrastructure required**
- **GitHub Actions** — lint, type-check, tests against real Postgres + Redis services, Docker image build
- **Docker Compose** — postgres, redis, backend, dashboard, with healthchecks and an entrypoint that waits for the DB, migrates, and bootstraps the superuser
- **VS Code** config — debug launchers for uvicorn / Streamlit / pytest, Ruff on save

---

## Quick start

```bash
git clone https://github.com/shenbagaramang/AITraderPro.git
cd AITraderPro

cp .env.example .env
# Generate a real secret:
sed -i '' "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" .env

docker compose up -d --build
```

| Service | URL |
| --- | --- |
| API docs (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |
| Dashboard | http://localhost:8501 |

Default superuser: `admin@aitraderpro.local` / `ChangeMe123!` — change it in `.env` before you expose anything.

### Local development without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt

docker compose up -d postgres redis   # infra only
export PYTHONPATH=backend
alembic upgrade head
uvicorn app.main:app --reload         # API on :8000
streamlit run dashboard/app.py        # dashboard on :8501
```

### Make targets

```bash
make up         # build and start the whole stack
make test       # pytest (no infra needed)
make check      # lint + typecheck + test, exactly what CI runs
make migrate    # alembic upgrade head
make revision m="add orders table"
make logs       # tail the backend
```

---

## Project layout

```
AITraderPro/
├── backend/app/
│   ├── main.py                 # app factory, middleware, lifespan
│   ├── core/                   # config, security, logging, exceptions, deps
│   ├── db/                     # engine, session, declarative base, bootstrap
│   ├── models/                 # User, RefreshToken, AuditLog
│   ├── schemas/                # pydantic request/response contracts
│   ├── crud/                   # data access, generic async CRUD base
│   ├── services/               # use-cases: auth_service, user_service
│   ├── api/v1/                 # health, auth, users routers
│   ├── middleware/             # request-id + latency logging
│   └── cache/                  # redis client, JWT blocklist
├── dashboard/                  # Streamlit: app.py, pages/, utils/api_client.py
├── migrations/                 # alembic env + versions/0001_initial_schema.py
├── tests/                      # unit/, integration/, API tests, conftest
├── docker/                     # Dockerfile.backend, Dockerfile.dashboard
├── scripts/                    # entrypoint.sh, create_superuser.py
├── .github/workflows/ci.yml
├── docker-compose.yml
├── pyproject.toml              # ruff, mypy, pytest, coverage config
└── Makefile
```

The layering is deliberate: **API → service → CRUD → model**. Routers never touch the ORM directly, services never build HTTP responses. When the Decision Engine arrives in Phase 4 it becomes another service, and the order router calls it exactly the way `auth.py` calls `auth_service` today.

---

## API surface (Phase 1)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/health` | — | Liveness + DB/Redis status |
| POST | `/api/v1/auth/register` | — | Create an account |
| POST | `/api/v1/auth/login` | — | Email/password → token pair |
| POST | `/api/v1/auth/token` | — | OAuth2 form flow (Swagger Authorize) |
| POST | `/api/v1/auth/refresh` | — | Rotate a refresh token |
| POST | `/api/v1/auth/logout` | Bearer | Revoke all active tokens |
| GET | `/api/v1/auth/me` | Bearer | Current user |
| PATCH | `/api/v1/users/me` | Bearer | Update own profile |
| POST | `/api/v1/users/me/password` | Bearer | Change password |
| GET | `/api/v1/users` | Admin | List users (paginated) |
| GET | `/api/v1/users/{id}` | Admin | Fetch a user |
| PATCH | `/api/v1/users/{id}` | Admin | Update a user |
| DELETE | `/api/v1/users/{id}` | Admin | Deactivate a user |

Errors are uniform, and every one carries the request id so a user report maps straight to a log line:

```json
{
  "error": { "code": "token_revoked", "message": "Token has been revoked" },
  "request_id": "a1b2c3d4e5f60718"
}
```

---

## Testing

```bash
make test                       # 31 tests, in-memory SQLite + fake Redis
pytest -m integration           # needs a live Postgres
make test-cov                   # coverage report
```

The suite covers password hashing and salting, JWT claim/type/expiry/tamper handling, refresh-token rotation and replay rejection, logout blocklisting, role guards, the self-escalation guard, and config URI construction.

---

## Roadmap

**Phase 2 — Zerodha Kite**: OAuth login flow and encrypted token vault, portfolio and holdings, order placement/modify/cancel with the audit trail already in place, KiteTicker WebSocket → Redis → dashboard.

**Phase 3 — TradingView MCP**: an MCP server exposing chart and analysis tools to Claude Desktop, Pine Script generation endpoints, webhook receiver for TradingView alerts.

**Phase 4a — Scanner engine (done)**: 12 indicators (EMA, SMA, RMA, RSI, MACD, ROC, Bollinger, ATR, True Range, Supertrend, VWAP, RVOL, OBV) with Pine-Script-compatible smoothing; six scanners (ema, breakout, volume, bollinger, momentum, vwap); a technical agent that aggregates them into a weighted view with explicit dissent.

**Phase 4b — Decision Engine**: risk agent, portfolio agent, position sizing, watchlists and the alerting pipeline.

## License

MIT — see [LICENSE](LICENSE).
