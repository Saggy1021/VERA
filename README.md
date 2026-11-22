# SENTINEL

**Smart Exam & Interview Proctoring Platform**

> Production-grade online proctoring platform with real-time AI monitoring.
> All inference runs in-browser via Web Workers — zero server-side ML models.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  CANDIDATE BROWSER                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │face_worker│  │obj_worker│  │aud_worker│  │  focus_monitor   │   │
│  │ MediaPipe │  │ COCO-SSD │  │ VAD RMS  │  │ visibility API   │   │
│  │ WASM/GPU  │  │ TF.js    │  │ baseline │  │ fullscreen API   │   │
│  └─────┬─────┘  └─────┬────┘  └─────┬────┘  └────────┬─────────┘   │
│        └───────────────┴──────────────┴───────────────┘             │
│                           │                                         │
│                    useSession.ts                                     │
│              (EWMA scoring engine)                                   │
│                    8fps frame loop                                   │
│                           │                                         │
│           ┌───────────────┴───────────────┐                         │
│           │  useEventReporter (batch 10s) │                         │
│           └───────────────┬───────────────┘                         │
└───────────────────────────┼─────────────────────────────────────────┘
                            │ REST + Socket.IO
┌───────────────────────────┼─────────────────────────────────────────┐
│  BACKEND (FastAPI)        │                                         │
│  ┌────────────────────────┴────────────────────────────────┐       │
│  │  /api/events/batch    /api/events/high    /api/sessions │       │
│  │  /api/reports         /api/audit          /health       │       │
│  └────────────┬───────────────────────┬────────────────────┘       │
│               │                       │                             │
│     ┌─────────┴──────┐    ┌──────────┴─────────┐                   │
│     │ gemini_service  │    │  groq_service      │                   │
│     │ (HIGH events)   │    │ (speech→text)      │                   │
│     │ 8s timeout      │    │ whisper-large-v3   │                   │
│     └────────────────┘    └────────────────────┘                   │
│               │                                                     │
│     ┌─────────┴──────────────────────────┐                         │
│     │ Supabase (PostgreSQL + Storage)    │                         │
│     └────────────────────────────────────┘                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer     | Technology                                  |
|-----------|---------------------------------------------|
| Frontend  | Next.js 15, TypeScript, Tailwind CSS        |
| State     | Zustand, React Query                        |
| Workers   | MediaPipe WASM, TF.js COCO-SSD, Web Audio  |
| Charts    | Chart.js + react-chartjs-2                  |
| Backend   | FastAPI, Python 3.12, asyncpg               |
| Realtime  | python-socketio (ASGI)                      |
| Database  | Supabase (PostgreSQL + RLS)                 |
| Storage   | Supabase Storage                            |
| AI (ext)  | Gemini 2.0 Flash, Groq Whisper large-v3     |
| Email     | Resend (free) / SMTP fallback               |
| Deploy    | Docker Compose                              |

## Detection Capabilities

| Detection                | Method                          | Worker        |
|--------------------------|--------------------------------|---------------|
| Face presence            | MediaPipe Face Landmarker      | face_worker   |
| Multiple faces           | MediaPipe (numFaces=3)         | face_worker   |
| Head pose (yaw/pitch)    | Landmark geometry              | face_worker   |
| Gaze direction           | Iris landmark tracking         | face_worker   |
| Blink rate               | Eye Aspect Ratio (EAR)        | face_worker   |
| Identity verification    | face-api.js cosine similarity  | face_worker   |
| Phone/book/laptop        | TF.js COCO-SSD MobileNet v2   | object_worker |
| Tab switching            | Page Visibility API            | focus_monitor |
| Fullscreen exit          | Fullscreen API                 | focus_monitor |
| Copy/paste/right-click   | DOM event interception         | focus_monitor |
| Speech activity          | RMS energy + baseline VAD      | audio_worker  |
| Speech transcription     | Groq Whisper (server-side)     | backend       |
| AI second opinion        | Gemini 2.0 Flash (HIGH only)   | backend       |

## Scoring Engine

- **EWMA smoothing** with α=0.3 (VERA used 0.45, caused false positives)
- **Persist-frame gating**: flag must be active for N consecutive frames before contributing
- **Weighted composite**: 10 flag channels with configurable weights summing to 1.0
- **Score decay**: 1.5 pts/frame when all flags clear (prevents score bouncing)
- **60-second sacred calibration window**: no flags emitted during calibration

## Project Structure

```
SENTINEL/
├── backend/
│   ├── auth/               # JWT validation, role guards
│   ├── db/
│   │   ├── migrations/     # 001_initial.sql (DDL + RLS)
│   │   └── queries.py      # Named SQL functions
│   ├── models/             # Pydantic models
│   ├── routers/            # FastAPI route handlers
│   ├── services/           # Gemini, Groq, Storage, Email
│   ├── websocket/          # Socket.IO manager + handlers
│   ├── config.py           # pydantic-settings env config
│   ├── database.py         # asyncpg pool management
│   ├── main.py             # App entry point
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── workers/            # Web Workers (face, object, audio, focus)
│   ├── src/
│   │   ├── app/            # Next.js App Router pages
│   │   │   ├── (auth)/     # Login, Register
│   │   │   ├── candidate/  # Dashboard, Setup, Session, Report
│   │   │   └── proctor/    # Dashboard, Sessions, Candidates, Reports
│   │   ├── components/     # React components
│   │   │   ├── candidate/  # CameraPreview, AudioMeter, StatusBar, etc.
│   │   │   ├── proctor/    # LiveGrid, AlertFeed, RiskTimeline, etc.
│   │   │   └── shared/     # ErrorBoundary, Navbar, LoadingSpinner
│   │   ├── hooks/          # Worker hooks, useSession, useEventReporter
│   │   ├── lib/            # supabase, api, constants, scoring, utils
│   │   └── store/          # Zustand stores
│   ├── next.config.ts
│   ├── package.json
│   └── Dockerfile
├── supabase/
│   ├── config.toml
│   └── migrations/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## Quick Start

### Prerequisites

- Node.js 20+
- Python 3.12+
- Docker & Docker Compose
- Supabase account (free tier works)

### 1. Clone & Configure

```bash
git clone <repo-url>
cd SENTINEL
cp .env.example .env
# Fill in your Supabase URL, keys, Gemini API key, Groq API key
```

### 2. Run Database Migration

Apply the migration SQL to your Supabase project:
- Go to Supabase Dashboard → SQL Editor
- Paste contents of `backend/db/migrations/001_initial.sql`
- Run

### 3. Start with Docker Compose

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend:  http://localhost:8000
- Health:   http://localhost:8000/health

### 4. Development (without Docker)

**Backend:**
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn main:socket_app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

## Environment Variables

| Variable                    | Required | Description                        |
|-----------------------------|----------|------------------------------------|
| `SUPABASE_URL`              | Yes      | Supabase project URL               |
| `SUPABASE_ANON_KEY`         | Yes      | Supabase anonymous key             |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes      | Supabase service role key          |
| `DATABASE_URL`              | Yes      | PostgreSQL connection string       |
| `JWT_SECRET`                | Yes      | Supabase JWT secret                |
| `GEMINI_API_KEY`            | Yes      | Google Gemini 2.0 Flash API key    |
| `GROQ_API_KEY`              | No       | Groq Whisper API key (optional)    |
| `RESEND_API_KEY`            | No       | Resend email API key (optional)    |

## Critical Design Decisions (from VERA post-mortem)

1. **No server-side ML models** — VERA loaded 7 models at startup (7GB RAM, 45s cold start). SENTINEL runs all inference in browser Web Workers.
2. **EWMA α=0.3** — VERA's 0.45 caused score bouncing and false positives on natural head movements.
3. **60-second calibration window** — VERA had no baseline; SENTINEL calibrates to each candidate's natural posture.
4. **Persist-frame gating** — flags must sustain for N frames before contributing to risk score, eliminating momentary false positives.
5. **Gemini only on HIGH events** — VERA called AI on every frame. SENTINEL calls Gemini only when risk exceeds threshold, with an 8s timeout and fail-safe (event is saved even if Gemini fails).
6. **Batch event reporting (10s)** — prevents API flooding during fast head movements.
7. **Score decay at 1.5 pts/frame** — VERA decayed at 4 pts/sec causing rapid score bouncing.

## API Endpoints

| Method | Path                                    | Auth       | Description                    |
|--------|----------------------------------------|------------|--------------------------------|
| GET    | `/health`                              | None       | Health check                   |
| POST   | `/api/sessions`                        | Proctor    | Create session                 |
| GET    | `/api/sessions`                        | Any        | List sessions (role-filtered)  |
| GET    | `/api/sessions/:id`                    | Proctor    | Get session details            |
| PUT    | `/api/sessions/:id`                    | Proctor    | Update session status          |
| POST   | `/api/sessions/:id/candidates`         | Proctor    | Invite candidate               |
| GET    | `/api/sessions/:id/candidates`         | Proctor    | List candidates                |
| POST   | `/api/setup/enroll`                    | Candidate  | Submit face descriptor         |
| POST   | `/api/events/batch`                    | Candidate  | Batch event ingest             |
| POST   | `/api/events/high`                     | Candidate  | HIGH event + screenshot        |
| GET    | `/api/sessions/:id/events`             | Proctor    | Get session events             |
| GET    | `/api/reports/:sid/:cid`               | Any        | Get report                     |
| POST   | `/api/reports/:sid/:cid/publish`       | Proctor    | Publish report to candidate    |
| POST   | `/api/reports/:sid/:cid/suppress`      | Proctor    | Suppress report                |
| GET    | `/api/audit`                           | Proctor    | Paginated audit log            |

## License

MIT
