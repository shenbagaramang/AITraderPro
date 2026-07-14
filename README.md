# AITraderPro

An AI-assisted algorithmic trading platform for Indian equity markets (NSE/BSE), built on a single FastAPI + Postgres + Redis foundation.

**All four phases below are implemented**, not just Phase 1 — auth/foundation, the Zerodha Kite broker integration, the TradingView-facing MCP server, and the scanner/agent/decision-engine stack all have working code, routes, and tests. See [What's not finished](#whats-not-finished) for the honest list of what's still thin.

---

## Target architecture

```
                                    +-----------------------+
                                    |   TradingView Desktop |
                                    |    (Charts & Alerts)  |
                                    +-----------+-----------+
                                                |
                                            MCP Server                  (mcp_server/)
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
 Scanner      Analyzer    Analyzer
    |           |           |                   |                 |
    +-----------+-----------+-------------------+-----------------+
                                |
                         Decision Engine
                                |
                +---------------+----------------+
                |                                |
         Zerodha Kite API                 Streamlit Dashboard
                |                                |
         Order Management                 PostgreSQL Database
```

Every box in this diagram has working code behind it today — nothing here is a
"planned" placeholder. See [What's not finished](#whats-not-finished) for the
genuine gaps.

### Where each phase plugs in

| Layer in the diagram | Phase | Status | Lands in |
| --- | --- | --- | --- |
| PostgreSQL, Streamlit shell, auth, config, logging | 1 | **Done** | `backend/app/`, `dashboard/` |
| Zerodha Kite API, Order Management | 2 | **Done** | `backend/app/brokers/kite/`, `backend/app/api/v1/broker.py`, `orders.py` |
| MCP Server, Claude Desktop, Pine Script generation | 3 | **Done** | `mcp_server/`, `backend/app/pine/`, `backend/app/api/v1/analysis.py` |
| Market Scanner, indicators, Technical Agent | 4a | **Done** | `backend/app/indicators/`, `scanners/`, `agents/technical_agent.py` |
| Risk & Portfolio Manager, Decision Engine | 4b | **Done** | `backend/app/engine/`, `agents/risk_agent.py`, `agents/portfolio_agent.py` |
| Fundamental/News agents + market context | 4a extra | **Done** | `backend/app/adapters/`, `agents/fundamental_agent.py`, `agents/news_agent.py` |
| Live tick fan-out into the dashboard | 2 extra | Backend only | `KiteTicker` publishes to Redis; no dashboard consumer yet |

### The scanner stack is layered, not flat

```
indicators/   pure math          ema(close, 9) -> Series
scanners/     criteria on math   "EMA9 crossed EMA21 on 2.3x volume" -> Signal
agents/       interpretation     "bullish, moderate, but volume disagrees" -> TechnicalView
engine/       decision           entry, stop, size -> Order
```

Each layer imports only from the layer below. That is what stops EMA from being
implemented three times and disagreeing — see [docs/LAYERING.md](docs/LAYERING.md).

Phase 1 built the parts every later phase leans on: identity (who is placing this order), persistence, cache, migrations, config, structured logging, and CI. Every later phase built on that foundation rather than stubbing around it — the broker, MCP server, scanners, and decision engine below are real modules, not fake abstractions waiting to be filled in.

---

## What is actually in the box

**Foundation (Phase 1)**
- **FastAPI backend**, versioned under `/api/v1`, application-factory pattern, OpenAPI at `/docs`
- **JWT authentication** — access + refresh tokens, refresh-token **rotation** (a replayed refresh token is rejected), logout via a **Redis blocklist**, refresh tokens stored as SHA-256 digests so a database leak cannot mint sessions
- **User management** — registration, profile updates, password change, role-based access (`admin` / `trader` / `viewer`), admin-only listing, privilege-escalation guard on self-update
- **PostgreSQL** via async SQLAlchemy 2.0 + **Alembic** migrations
- **Redis** for the token blocklist, quote caching and tick fan-out
- **Audit log** table — every login, failed login, logout and order event is recorded
- **Structured logging** — request-id ContextVar on every log line, JSON mode for production, latency on every request
- **GitHub Actions** — lint, type-check, tests against real Postgres + Redis services, Docker image build
- **Docker Compose** — postgres, redis, backend, dashboard, with healthchecks and an entrypoint that waits for the DB, migrates, and bootstraps the superuser
- **VS Code** config — debug launchers for uvicorn / Streamlit / pytest, Ruff on save

**Broker integration (Phase 2)** — `backend/app/brokers/`
- **Zerodha Kite** — daily OAuth-style login flow, tokens encrypted at rest (Fernet, key separate from `SECRET_KEY`), positions/holdings/margins/quotes
- **Paper broker** — same interface as Kite, deterministic fills with slippage, so a strategy tested on paper touches the exact code path a live order will
- **Order management** — place/cancel, idempotency keys (a Streamlit rerun can't double-submit), full audit trail, a `LIVE_TRADING_ENABLED` kill switch that defaults to off
- **KiteTicker** — WebSocket tick stream fanned out to Redis (`ticks:{SYMBOL}`); nothing consumes it in the dashboard yet, see [What's not finished](#whats-not-finished)

**MCP server + Pine generation (Phase 3)** — `mcp_server/`, `backend/app/pine/`
- A `FastMCP` server for Claude Desktop that is a **thin client of the REST API** — same auth, same role checks, same kill switch, same audit log as the dashboard, no second door into the database
- Tools: technical analysis, the full decision engine, Pine v6 script generation, paper order placement (hard-coded to paper — live orders only go through the dashboard), portfolio/quotes/health
- **Pine Script generator** — produces v6 scripts whose parameters and smoothing match the Python scanners exactly, so a TradingView alert and a platform signal agree
- **Webhook receiver** (`/api/v1/webhooks/tradingview`) — accepts TradingView alerts guarded by a shared secret (`TRADINGVIEW_WEBHOOK_SECRET`)

**Scanner engine + agents (Phase 4)** — `backend/app/indicators/`, `scanners/`, `agents/`, `engine/`
- 15 indicators (EMA, SMA, RMA, RSI, MACD, ROC, Bollinger Bands, ATR, True Range, Supertrend, VWAP, Relative Volume, OBV, ADX, Ichimoku) with Pine-Script-compatible smoothing
- 8 scanners (ema, breakout, volume, bollinger, momentum, vwap, adx, ichimoku), a registry that runs the full battery and downgrades a failing scanner to neutral instead of losing the rest
- **Technical agent** — aggregates the 8 scanners into a weighted bias/conviction view with explicit dissent when scanners disagree
- **Risk agent** — position sizing, stops, R:R, correlation limits, and a hard veto
- **Portfolio agent** — CAGR, drawdown, Sharpe, Sortino, win ratio, concentration
- **Fundamental agent** — composite score from Yahoo Finance data, with explicit `data_caveats` about what Yahoo can't tell you (promoter holding/pledge, FII/DII flows)
- **News agent** — headline sentiment from Google News RSS, lexicon classifier, no API key required
- **Decision engine** — technical proposes, risk can veto, position sized against account equity; the default answer is no-trade
- **Watchlists + alert inbox** — state-change alerts only (a signal that already fired doesn't re-alert every scan)

**Dashboard** — `dashboard/`
- Login/register, session handling with silent token refresh, health indicator (API/DB/Redis)
- **Overview** — paper or live positions, holdings, margins, P&L
- **Trade** — order ticket (market/limit/SL-M), quotes, order book, paper account reset
- **Broker** — Kite daily login flow, live holdings/positions/margins
- **Scanner** — alert inbox, scan results, watchlist CRUD
- **Analysis** — technical view and decision engine against uploaded/pasted OHLCV, Pine script generation with download
- **Research** — fundamentals, news, and market-context (Nifty/VIX/USD-INR/crude) lookups

**Tests** — 236 test functions across `tests/unit/` and `tests/` (auth, users, health, broker/orders, analysis, scanners, decision engine, agents, adapters), runnable against in-memory SQLite with **zero infrastructure required**

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

Default superuser: `admin@aitraderpro.dev` / `ChangeMe123!` — change it in `.env` before you expose anything.

### Local development without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt

docker compose up -d postgres redis   # infra only
export PYTHONPATH=backend
alembic upgrade head
uvicorn app.main:app --reload         # API on :8000
streamlit run dashboard/Home.py       # dashboard on :8501
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
│   ├── models/                 # User, RefreshToken, AuditLog, Order, BrokerCredential, Watchlist, Alert, ScanResult
│   ├── schemas/         # pydantic request/response contracts
│   ├── crud/            # data access, generic async CRUD base
│   ├── services/        # use-cases: auth, user, broker, order, candle, scan
│   ├── api/v1/          # health, auth, users, broker, orders, analysis, research, scanner, webhooks
│   ├── middleware/      # request-id + latency logging
│   ├── cache/           # redis client, JWT blocklist
│   ├── brokers/         # broker interface, paper broker, brokers/kite/ (auth, client, ticker)
│   ├── indicators/      # pure-math indicators (EMA, RSI, MACD, ADX, Ichimoku, ...)
│   ├── scanners/        # signal criteria on top of indicators (8 scanners + registry)
│   ├── agents/          # technical, risk, portfolio, fundamental, news agents
│   ├── adapters/        # Yahoo Finance, Google News RSS, sentiment classifier, TTL cache
│   ├── engine/          # decision engine (proposes -> vetoes -> sizes)
│   └── pine/            # Pine v6 script generator
├── mcp_server/          # FastMCP server for Claude Desktop (thin REST client)
├── dashboard/           # Streamlit: Home.py, pages/ (Login, Overview, Settings, Trade,
│                        # Broker, Scanner, Analysis, Research), utils/api_client.py
├── migrations/          # alembic env + versions/0001-0004
├── tests/               # unit/, integration/, API tests, conftest
├── docker/              # Dockerfile.backend, Dockerfile.dashboard
├── scripts/             # entrypoint.sh, create_superuser.py
├── .github/workflows/ci.yml
├── docker-compose.yml
├── pyproject.toml       # ruff, mypy, pytest, coverage config
└── Makefile
```

The layering is deliberate: **API → service → CRUD → model**, and **indicators → scanners → agents → engine**. Routers never touch the ORM directly, services never build HTTP responses, and the decision engine consumes agent output the same way the order router calls `auth_service` — no shortcuts across layers.

---

## API surface

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
| GET/PATCH/DELETE | `/api/v1/users`, `/users/{id}` | Admin | List/update/deactivate users |
| GET | `/api/v1/broker/status` | Bearer | Kite session status |
| GET | `/api/v1/broker/kite/login-url` | Bearer | Start the daily Kite login |
| POST/DELETE | `/api/v1/broker/kite/session` | Bearer | Complete login / disconnect |
| GET | `/api/v1/broker/{positions,holdings,margins,quotes}` | Bearer | Paper or live book (`?paper=`) |
| POST | `/api/v1/broker/paper/reset` | Bearer | Reset the paper account |
| POST/GET/DELETE | `/api/v1/orders`, `/orders/{id}` | Bearer | Place, list, fetch, cancel orders |
| POST | `/api/v1/analysis/technical` | Bearer | Run all scanners + the technical agent |
| POST | `/api/v1/analysis/decide` | Bearer | Run the full decision engine |
| GET/POST | `/api/v1/analysis/pine`, `/pine/templates` | Bearer | List / generate Pine v6 scripts |
| GET | `/api/v1/research/fundamental/{symbol}` | Bearer | Yahoo-backed fundamental score |
| GET | `/api/v1/research/news/{symbol}` | Bearer | Google-News-backed sentiment |
| GET | `/api/v1/research/context` | Bearer | Nifty/VIX/USD-INR/crude backdrop |
| GET/POST/PUT/DELETE | `/api/v1/scanner/watchlists` | Bearer | Watchlist CRUD |
| POST | `/api/v1/scanner/watchlists/{id}/scan` | Bearer | Run the scanner battery on a watchlist |
| GET | `/api/v1/scanner/{results,alerts}` | Bearer | Scan history / alert inbox |
| POST | `/api/v1/scanner/alerts/ack` | Bearer | Acknowledge alerts |
| POST | `/api/v1/webhooks/tradingview` | Shared secret | TradingView alert intake |

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
make test                       # 236 tests, in-memory SQLite + fake Redis
pytest -m integration           # needs a live Postgres
make test-cov                   # coverage report
```

The suite covers password hashing and salting, JWT claim/type/expiry/tamper handling, refresh-token rotation and replay rejection, logout blocklisting, role guards, the self-escalation guard, config URI construction, the paper broker and Kite adapter, every indicator/scanner, the technical/risk/portfolio/fundamental/news agents, the decision engine, and Pine generation.

---

## What's not finished

This is the honest gap list — everything not here is real, working code:

- **Historical candles are caller-supplied.** The analysis and scanner endpoints take OHLCV inline (upload/paste in the dashboard); there's no free intraday data source wired in server-side, and Kite's historical API is a paid add-on most keys don't have.
- **Live ticks don't reach the dashboard.** `KiteTicker` publishes to Redis (`ticks:{SYMBOL}`), but nothing in the Streamlit app subscribes — the Trade/Broker/Overview pages poll the REST quote endpoint instead.
- **`TRADINGVIEW_WEBHOOK_SECRET` is missing from `.env.example`** even though `core/config.py` reads it and the webhook route requires it to be non-empty.
- Fundamental/news adapters are Yahoo Finance / Google News RSS only — no NSE filings, promoter holding/pledge, or FII/DII data (the fundamental agent's `data_caveats` field says so explicitly on every response).

## License

MIT — see [LICENSE](LICENSE).
