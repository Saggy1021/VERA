# SENTINEL Live Failure Findings Report
**Audit Type:** Read-Only End-to-End Diagnostic  
**Date:** 2026-11-23  
**Build State:** TypeScript 0 errors · Production build green (11/11 routes)  
**Demo Session:** `d3b07384-d113-4f44-93c0-3051187d7b3e` (confirmed `active` in DB)  
**Auditor Note:** No code was modified during this audit. All findings are based on static analysis with exact file/line evidence.

---

## Executive Summary

| Issue | Root Cause Category | Severity | Fix Effort |
|-------|-------------------|----------|------------|
| 1. HUD stuck on `Loading`, `Risk 0`, no alerts | COCO-SSD model 404 + race condition in `startSession` | 🔴 Critical | ~30 min |
| 2. Proctor shows candidate offline, no thumbnail | Race condition: `connect()` fires before `session` loads | 🔴 Critical | ~15 min |
| 3. Session end doesn't stop candidate | No Socket.IO `session_ended` broadcast + no candidate listener | 🟠 High | ~20 min |
| 4. General signal drops (scoring, heartbeat) | 5 compounding bugs in EWMA math, heartbeat token async, CORS config | 🔴 Critical | ~1 hr |

**All four issues are fixable today.** None require architecture changes.

---

## Issue 1 — Objects Stuck on `Loading` / Risk Score Always 0 / No Alerts

### Root Cause A: COCO-SSD Model Not Present in `public/`

**Evidence:**
- [`object_worker.ts:52-67`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/workers/object_worker.ts#L52-L67): The `INIT` handler dynamically imports `@tensorflow/tfjs` and `@tensorflow-models/coco-ssd`, then calls `cocoSsd.load({ base: 'lite_mobilenet_v2' })`. This triggers a **CDN fetch** to `https://tfhub.dev/...` or the `modelPath` passed in the `INIT` message.
- [`useObjectWorker.ts:70`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useObjectWorker.ts#L70): `worker.postMessage({ type: 'INIT', modelPath: '/models/coco_ssd/' })` — passes a local path.
- **`public/models/` directory contains:**
  ```
  public/models/wasm/
  public/models/face_landmarker.task   (3.7 MB)
  public/models/vision_wasm_internal.js
  public/models/vision_wasm_internal.wasm
  ```
- **`public/models/coco_ssd/` does NOT exist.** The COCO-SSD package will fall back to fetching from TF Hub CDN. In a demo environment with no internet access or cold network, this fetch hangs or fails silently inside the Worker.
- [`object_worker.ts:46-70`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/workers/object_worker.ts#L46-L70): If `cocoSsd.load()` throws or times out, the `catch` block at line 153 posts `{ type: 'ERROR' }` — but `useObjectWorker.ts:45-47` only logs the error; `isReady` **stays `false` permanently** (no retry path in `ERROR` handler).
- [`candidate/session/page.tsx:481`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/app/candidate/session/%5BsessionId%5D/page.tsx#L481): HUD renders `{session.objectWorker.isReady ? session.liveLastObject : 'Loading'}`. Since `isReady` never becomes `true`, it always shows **`Loading`** — confirmed root cause for the observed symptom.

**Fix:** Download and serve COCO-SSD lite model files locally in `frontend/public/models/coco_ssd/`, or remove the custom `modelPath` and ensure CDN access. See Fix Plan below.

---

### Root Cause B: Face Worker `isReady` Gating Prevents First Frames

**Evidence:**
- [`useSession.ts:651`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useSession.ts#L651): `if (tick % 2 === 0 && faceWorker.isReady && !faceInFlightRef.current)` — face analysis only runs when `faceWorker.isReady === true`.
- The face worker (`face_landmarker.task`, 3.7 MB) is loaded from `public/models/`. MediaPipe WASM initialization typically takes **2–5 seconds** on first load. During this window, `isReady` is `false` and the `frameLoopRef` interval at 125ms fires every tick — but all face ticks are dropped silently.
- **This is correct defensive behavior**, but it means: if the MediaPipe model loads slowly on demo hardware, face analysis begins late. Combined with the 60-second calibration window (`calibrationRef`), **the first 60+ seconds of a session produce zero risk score and zero alerts**.
- The issue compounds: `faceWorker.isReady` is a React `useState` boolean in `useFaceWorker.ts`. Because `faceWorker` is a dependency of `startSession`'s `useCallback`, and `startSession` captures `faceWorker` at call time — the `isReady` value read inside the interval closure is a **stale closure capture** from when `startSession` ran. React `useCallback` with `[..., faceWorker]` as deps will re-create `startSession` when `isReady` changes, but the **interval itself** (`frameLoopRef.current`) is set once and not reset.

**Fix:** Read `faceWorker.isReady` via a ref (`faceWorkerReadyRef.current`) updated by a `useEffect`, so the closure always has the live value. OR clear and re-set the interval when workers become ready.

---

### Root Cause C: EWMA `no_face` Score Math — Score Is Correct But Requires Full 60s Calibration

**Evidence:**
- [`scoring.ts:60-64`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/lib/scoring.ts#L60-L64):
  ```ts
  const persistOk = (state.persistCounters[flagKey] ?? 0) >= config.persistFrames;
  if (persistOk && smoothedVal >= config.threshold) {
    score += smoothedVal * contribution;
  }
  ```
- [`constants.ts:29`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/lib/constants.ts#L29): `no_face: { threshold: 0.5, persistFrames: 4 }` — requires **4 consecutive frames** of `no_face=1` before it contributes.
- At 4fps face analysis (every 2nd tick at 8fps), 4 frames = **1 second** of continuous absence. This is intentional.
- BUT [`useSession.ts:499`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useSession.ts#L499): Inside the audio worker handler: `if (!calibrationRef.current.isCalibrated) return;` — audio events are silently suppressed during the 60s calibration window. This is intentional but means early audio violations are lost.
- [`useSession.ts:277`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useSession.ts#L277): `head_turned` and `gaze_away` flags both check `cal.isCalibrated` — they produce `0` (no contribution) during calibration. Only `no_face`, `multiple_faces`, `identity_mismatch` are active immediately.
- **Summary:** Scoring math is correct. `no_face` WILL score (45 × EWMA ≈ 31 pts after 1 second). The score stays at 0 only if the face worker never fires — which is caused by Root Cause A/B above.

---

### Root Cause D: `startSession` Called Before Camera Stream Is Ready

**Evidence:**
- Candidate page calls `session.startSession(stream)` from `handleStreamReady` in `CameraPreview`. If the camera permission is delayed or the user is slow to allow it, `startSession` may be called with `cameraStream = undefined`, meaning the circular buffer never starts AND `captureDownscaledBitmap` returns `null` every tick (because `video.readyState < 2`).
- [`useSession.ts:350`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useSession.ts#L350): `if (!video || video.readyState < 2) return null;` — bitmap returns null, no frame is dispatched.

---

### Severity
🔴 **Critical** — The entire ML proctoring pipeline produces zero output until these are fixed.

### Fix Plan
1. **Model hosting (30 min):** Run `npx @tensorflow/tfjs-converter` or download the COCO-SSD `lite_mobilenet_v2` model JSON + shard files and place them in `frontend/public/models/coco_ssd/`. Pass that path in the `INIT` message so the worker loads locally.
2. **Stale closure (15 min):** Add `const faceWorkerReadyRef = useRef(faceWorker.isReady); useEffect(() => { faceWorkerReadyRef.current = faceWorker.isReady; }, [faceWorker.isReady]);` and change the interval check to `faceWorkerReadyRef.current`.
3. **Same pattern for objectWorker** — `objectWorkerReadyRef`.
4. **Fallback:** If COCO-SSD CDN fetch must remain, add a 15-second timeout in the `INIT` handler that posts `{ type: 'READY' }` anyway with `model = null`, then `ANALYZE_FRAME` returns empty detections. This keeps `isReady = true` and shows `Clear` instead of `Loading`.

---

## Issue 2 — Proctor Shows Candidate Offline / No Live Thumbnail

### Root Cause A: `connect()` Races Against Async Session Fetch

**Evidence:**
- [`proctor/sessions/page.tsx:171-176`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/app/proctor/sessions/%5BsessionId%5D/page.tsx#L171-L176):
  ```tsx
  useEffect(() => {
    if (session?.status === 'active') {
      connect();
    }
    return () => { disconnect(); };
  }, [session?.status, connect, disconnect]);
  ```
- [`proctor/sessions/page.tsx:97-109`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/app/proctor/sessions/%5BsessionId%5D/page.tsx#L97-L109): `session` is fetched asynchronously. Initial value is `null`.
- **On first render:** `session` is `null`, so `session?.status` is `undefined`. The `useEffect` fires with `undefined !== 'active'` → `connect()` is NOT called. ✓ (this is expected)
- **After fetch completes:** `session.status = 'active'` → `useEffect` fires again → `connect()` IS called. ✓ (this should work)
- **BUT:** `connect` and `disconnect` are both in the `useEffect` dependency array. `useProctorSocket` returns new stable references via `useCallback`, so they should be stable. **This part looks correct in isolation.**
- **Real problem:** `useProctorSocket.connect()` calls `supabase.auth.getSession()` async before creating the socket. If the Supabase session is expired or `NEXT_PUBLIC_SUPABASE_ANON_KEY` is wrong, `const { data: { session } } = await supabase.auth.getSession()` returns `session = null`, and [`useProctorSocket.ts:21`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useProctorSocket.ts#L21) `if (!session) return;` — **socket is never created**.

---

### Root Cause B: Candidate Heartbeat Never Delivers Token to Backend Auth

**Evidence:**
- [`useSession.ts:596-628`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useSession.ts#L596-L628):
  ```ts
  const socketUrl = process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:8000';
  const socket = io(socketUrl, { transports: ['websocket', 'polling'] });
  socketRef.current = socket;
  
  supabase.auth.getSession().then(({ data: { session: authSession } }) => {
    if (!authSession) return;   // ← SILENT EXIT if Supabase session is null/expired
    // heartbeat interval is set here
  });
  ```
- If `authSession` is `null` (token expired, or Supabase not initialized), **the heartbeat interval is never set**. The socket connects but never emits `candidate_heartbeat`. The backend never receives a heartbeat, so it never broadcasts `candidate_status`, and the proctor sees the candidate as offline.
- **Env var check:** `frontend/.env.local` confirmed to have `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_SOCKET_URL` — all present. So if the user is not logged in (session expired), this silently fails.

---

### Root Cause C: Backend `candidate_heartbeat` Broadcasts to `session:{id}` Room — But Proctor May Not Be In That Room Yet

**Evidence:**
- [`handlers.py:55-71`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/../backend/websocket/handlers.py#L55-L71): `candidate_heartbeat` broadcasts `candidate_status` to `room = f"session:{session_id}"`.
- [`handlers.py:100-101`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/backend/websocket/handlers.py#L100-L101): Proctor joins `session:{session_id}` only after emitting `join_proctor_room`. If candidate heartbeat fires **before** the proctor joins the room, those status broadcasts are lost (no message queuing). The proctor only sees the NEXT heartbeat after joining.
- With a 1.5s heartbeat interval, the proctor sees live status within 1.5 seconds of joining. **This is not a critical bug** — it just means the first 1-2 seconds appear offline.
- **Critical case:** If `candidate_heartbeat` backend auth (`validate_token`) fails (expired candidate JWT), the handler returns at line 52 `return` — no room join, no broadcast. The proctor sees offline permanently.

---

### Root Cause D: `main.py` CORS Config Mismatch

**Evidence:**
- [`main.py:16`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/backend/main.py#L16): `sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')` — Socket.IO CORS is `'*'` (all origins). ✓
- [`main.py:42-48`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/backend/main.py#L42-L48): FastAPI CORS uses `settings.cors_origins`.
- [`config.py:24`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/backend/config.py#L24): `cors_origins: List[str] = ["http://localhost:3000"]` — default is localhost:3000. If the backend `.env` overrides this with a different value or empty list, REST calls from the frontend fail with CORS errors, breaking `apiClient` and all API calls.
- **Socket.IO is fine** (`'*'`), but REST API (session fetch, event POST) depends on `CORS_ORIGINS` env var being set correctly in `backend/.env`.

---

### Severity
🔴 **Critical** — Proctor cannot monitor candidates without live status/thumbnail.

### Fix Plan
1. **Token expiry (10 min):** In `useSession.ts` heartbeat setup, add a retry: if `authSession === null`, call `supabase.auth.refreshSession()` and retry once. If still null, log a visible error.
2. **Proctor auth (10 min):** Same fix in `useProctorSocket.ts` connect — if session is null, attempt refresh before returning.
3. **CORS (5 min):** Ensure `backend/.env` sets `CORS_ORIGINS=http://localhost:3000` (or whatever the frontend URL is). The `config.py` default is correct for local dev.
4. **Heartbeat before join (not a bug):** No fix needed. 1.5s delay is acceptable.

---

## Issue 3 — Session End on Proctor Does NOT Stop Candidate

### Root Cause: No `session_ended` Socket.IO Broadcast

**Evidence:**
- [`proctor/sessions/page.tsx:191-200`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/app/proctor/sessions/%5BsessionId%5D/page.tsx#L191-L200): `handleEndSession` calls `PATCH /api/sessions/{id}/status` with `{ status: 'completed' }`, then calls `disconnect()` on the proctor socket.
- **Backend `PATCH /api/sessions/{id}/status`:** This updates the database row only. There is **no Socket.IO emit** in the sessions router when status changes. No `session_ended` or `session_status_changed` event is broadcast to the session room.
- [`handlers.py`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/backend/websocket/handlers.py): Full file has `connect`, `candidate_heartbeat`, `join_proctor_room`, `disconnect`, `send_warning`. **No `session_ended` handler exists.**
- [`candidate/session/page.tsx`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/app/candidate/session/%5BsessionId%5D/page.tsx): The candidate page does **not** listen for any socket event about session status. It has no polling for `/api/sessions/{id}` to detect completion.
- Result: When proctor clicks "End Session", the DB is updated to `completed`, but the candidate's browser **continues running indefinitely** — the frame loop, heartbeat, circular buffer, and exam timer all keep going.

### Additional Evidence — Candidate's Only Termination Path is Timer
- [`candidate/session/page.tsx:67-76`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/app/candidate/session/%5BsessionId%5D/page.tsx#L67-L76): The `IsolatedCountdownTimer` calls `onTimeExpired()` when timer hits 0. This is the ONLY way the candidate session auto-terminates.

### Severity
🟠 **High** — Candidates continue exam after proctor ends it; no way to force-terminate remotely.

### Fix Plan
1. **Backend (10 min):** In the sessions router `PATCH /status` handler, after updating DB, import `sio` from `main.py` and emit `session_ended` to the session room:
   ```python
   from main import sio
   await sio.emit('session_ended', {'sessionId': session_id, 'status': new_status}, room=f"session:{session_id}")
   ```
2. **Candidate socket listener (5 min):** In `useSession.ts`, add inside the socket setup:
   ```ts
   socket.on('session_ended', () => {
     stopSession();
     window.location.href = '/candidate/dashboard';
   });
   ```
3. **Fallback polling (optional, 5 min):** In the candidate page, poll `GET /api/sessions/{id}` every 30 seconds and redirect if `status !== 'active'`. Belt-and-suspenders for when socket fails.

---

## Issue 4 — General End-to-End Signal Drops

### Sub-issue 4A: `encodeWAV` Defined Inside Hook File but Outside Component — Stale `apiClient` Import Risk

**Evidence:**
- [`useSession.ts:117-149`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useSession.ts#L117-L149): `encodeWAV` is defined at module-scope **inside** the `useSession` function body but before `captureThumbnail`. It's indented inside `useSession` (not module-level) due to the indentation at line 117 (`function encodeWAV`). This creates a **function declaration inside a function** — valid JS/TS, but `encodeWAV` is re-created on every render. No performance impact, but confirms no closure bugs here.
- `apiClient` imported at top of file — this is stable. ✓

---

### Sub-issue 4B: `useSession.ts` `startSession` Callback Stability — Re-creation on Every `faceWorker.isReady` Change

**Evidence:**
- [`useSession.ts:676-680`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useSession.ts#L676-L680): `startSession` deps include `faceWorker`. Since `faceWorker` is the entire hook return value from `useFaceWorker()`, and `useFaceWorker` returns new object references on each render, `faceWorker` is a new object every render, causing `startSession` to be re-created on every render.
- If the candidate page calls `session.startSession(stream)` once (correctly), and then `faceWorker.isReady` changes from `false` → `true` (causing a re-render), `startSession` is now a new function. But the **page already called the old `startSession`** — the new one is never called. This is fine behavior-wise (session already started), but it means `useCallback` deps churn generates unnecessary object creation.
- **More importantly:** The old `startSession` closed over `faceWorker.isReady = false`. The interval at line 647 checks `faceWorker.isReady` — but this is the **stale `faceWorker` object** captured when `startSession` was called. When `isReady` becomes `true` on the NEW `faceWorker` object, the old interval closure never sees it.

**This is confirmed Root Cause for "face analysis never fires even after model loads"** — the stale closure sees the old `faceWorker` with `isReady: false`.

---

### Sub-issue 4C: Scoring Decay Logic Bug

**Evidence:**
- [`scoring.ts:69-72`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/lib/scoring.ts#L69-L72):
  ```ts
  const allClear = Object.values(state.persistCounters).every(c => c === 0);
  if (allClear) {
    score = Math.max(0, (state.lastScore ?? 0) - SCORE_DECAY_PER_FRAME);
  }
  ```
- When a flag fires and `persistCounters.no_face >= 4`, `score` is set by the `persistOk` branch. Then `allClear` is `false` (counter is 4), so the decay branch does NOT run. ✓
- When the face returns, `persistCounters.no_face` decrements by 2 per frame. At frame 1 after return: counter = 2, `allClear = false`, but `persistOk` is false (counter < 4), so score = 0 from the loop... then `allClear` is false... **score stays at whatever the decayed value was from `state.lastScore`**.
- **Bug:** `score` starts at 0 each call (loop only adds when `persistOk` is true). When `persistOk` is false and `allClear` is false, `score = 0` is returned immediately without decay being applied. This means a score of 85 drops to **0 instantly** when flags clear but counters haven't fully drained to 0 yet.
- **User impact:** Risk score may flash 85 → 0 instead of decaying smoothly. This creates a confusing display but doesn't block core functionality.

---

### Sub-issue 4D: Backend JWT Role Extraction — Supabase `user_metadata` vs `app_metadata`

**Evidence:**
- [`jwt_validator.py:84-86`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/backend/auth/jwt_validator.py#L84-L86):
  ```python
  role = user_metadata.get("role") or app_metadata.get("role") or payload.get("role", "")
  ```
- Supabase tokens have `role` in `user_metadata` (set during signup) or `app_metadata` (set server-side). If neither is present, `payload.get("role")` returns the Supabase system role (`"authenticated"`) — which fails the `if role not in ("proctor", "candidate")` check at line 89.
- **Impact:** Any user who was created without explicitly setting their `user_metadata.role` to `"proctor"` or `"candidate"` will get a 401 on ALL backend API calls. The candidate heartbeat in `handlers.py:49` calls `validate_token(token)` — if this 401s, the entire heartbeat is silently dropped.

---

### Sub-issue 4E: `useEventReporter.stopAutoFlush()` Final Beacon — Supabase Import is Async

**Evidence:**
- [`useEventReporter.ts:137-152`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useEventReporter.ts#L137-L152): The final flush on session stop uses `import('@/lib/supabase').then(...)` — a dynamic import. If the page is unloading, the dynamic import may never resolve. `navigator.sendBeacon` is called inside the Promise chain, but `sendBeacon` must be called synchronously on `beforeunload`. **Final events may be lost on tab close.**

---

### Sub-issue 4F: `useFocusWorker` Imports `FocusMonitor` on Main Thread

**Evidence:**
- [`useFocusWorker.ts:7`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/src/hooks/useFocusWorker.ts#L7): `import { FocusMonitor } from '../../workers/focus_worker'` — this imports the class directly into the main thread, not as a Web Worker. This is intentional (focus events need DOM access), but adds to main thread work. Not a bug.

---

### Sub-issue 4G: MediaPipe Worker Uses `Cross-Origin-Embedder-Policy: credentialless`

**Evidence:**
- [`next.config.ts:21`](file:///c:/Users/sagni/OneDrive/Desktop/LIFE%20MISTAKES!!!/SENTINEL/frontend/next.config.ts#L21): `{ key: 'Cross-Origin-Embedder-Policy', value: 'credentialless' }` — required for `SharedArrayBuffer` / WASM SIMD. `credentialless` allows cross-origin resources without credentials. This is the correct value for MediaPipe.
- If `COEP` is set to `require-corp` instead, the CDN-loaded TF.js COCO-SSD model fetch would fail with CORP error. `credentialless` avoids this. ✓

---

### Severity
🔴 **Critical (4B)** · 🟡 Medium (4C) · 🟡 Medium (4D) · 🟡 Medium (4A, 4E, 4F, 4G)

### Fix Plan for 4B (Most Critical)
Replace `faceWorker` and `objectWorker` direct object refs in the interval with refs:
```ts
// In useSession.ts, add:
const faceWorkerRef = useRef(faceWorker);
useEffect(() => { faceWorkerRef.current = faceWorker; }, [faceWorker]);
const objectWorkerRef = useRef(objectWorker);
useEffect(() => { objectWorkerRef.current = objectWorker; }, [objectWorker]);

// In the frameLoopRef interval, change:
// OLD: faceWorker.isReady
// NEW: faceWorkerRef.current.isReady
```

---

## Priority Fix Order

| Priority | Fix | File(s) | Est. Time |
|----------|-----|---------|-----------|
| P0 | Serve COCO-SSD model locally (`public/models/coco_ssd/`) | `useObjectWorker.ts`, `object_worker.ts` | 30 min |
| P0 | Fix stale closure on `faceWorker.isReady` and `objectWorker.isReady` in frame loop | `useSession.ts` | 15 min |
| P1 | Emit `session_ended` from backend PATCH handler + candidate socket listener | `backend/routers/sessions.py`, `useSession.ts` | 20 min |
| P1 | Supabase session refresh fallback in heartbeat setup + proctor connect | `useSession.ts`, `useProctorSocket.ts` | 10 min |
| P2 | Fix scoring decay — apply decay when `persistOk=false` but `lastScore > 0` | `scoring.ts` | 10 min |
| P2 | Verify `user_metadata.role` is set for all test users in Supabase | Supabase Dashboard | 5 min |
| P3 | Fix final beacon — call `sendBeacon` synchronously, resolve token from closure | `useEventReporter.ts` | 15 min |

---

## End-to-End Signal Flow (For Reference)

```
Candidate Browser                 Backend (FastAPI + Socket.IO)         Proctor Browser
─────────────────                 ─────────────────────────────         ───────────────
1. CameraPreview streams
2. startSession(stream)
   ├─ faceWorker.init()           
   ├─ objectWorker.init()  ───── COCO-SSD loads (may 404!) ──────────► [Loading stuck]
   ├─ io(SOCKET_URL) ──────────► connect (sio)
   │   └─ candidate_heartbeat ─► validate_token
   │       └─ enter_room ───────► emit candidate_status ─────────────► candidate_status
   │                                                                      └─ updateCandidate()
   └─ frameLoopRef (125ms)
       ├─ faceWorker.send() ────► ANALYZE_FRAME
       │   └─ FRAME_RESULT ◄──── face_worker.ts
       │       └─ updateRiskEWMA()
       │       └─ computeCompositeScore()
       │       └─ [if risk >= 75] triggerHighAlert()
       │           └─ sendHighEvent() ──────────────────────────────► POST /api/events/high
       │                                                                └─ emit candidate_event ► proctor
       └─ objectWorker.send() ──► ANALYZE_FRAME (if isReady)
           └─ FRAME_RESULT ◄──── object_worker.ts (COCO-SSD)

Proctor: PATCH /api/sessions/:id/status (completed)
   ├─ DB updated ✓
   └─ [MISSING] emit session_ended ──────────────────────────────────► [NO LISTENER ON CANDIDATE]
```

---

## Files Audited (Read-Only)

| File | Lines | Key Finding |
|------|-------|-------------|
| `frontend/workers/object_worker.ts` | 159 | COCO-SSD loads from CDN via `cocoSsd.load()`, no local fallback |
| `frontend/src/hooks/useObjectWorker.ts` | 104 | `isReady` stays `false` on ERROR; `INIT` posts `/models/coco_ssd/` (dir doesn't exist) |
| `frontend/src/hooks/useSession.ts` | 740 | Stale closure on `faceWorker.isReady` in interval; heartbeat needs live Supabase session |
| `frontend/src/hooks/useProctorSocket.ts` | 141 | `connect()` returns if Supabase session is null |
| `frontend/src/hooks/useFocusWorker.ts` | 47 | Correct — main thread DOM listener |
| `frontend/src/hooks/useEventReporter.ts` | 157 | Final beacon uses async import (may fail on unload) |
| `frontend/src/lib/api.ts` | 23 | Correct — axios with Supabase JWT interceptor |
| `frontend/src/lib/scoring.ts` | 75 | Score decay logic drops instantly when `persistCounters > 0` but `persistOk = false` |
| `frontend/src/lib/constants.ts` | 116 | `no_face` threshold/persistFrames correct; decay 1.5 pts/sec correct |
| `frontend/src/app/candidate/session/[sessionId]/page.tsx` | 541 | No socket listener for `session_ended`; no polling for session status |
| `frontend/src/app/proctor/sessions/[sessionId]/page.tsx` | 403 | `connect()` gated on `session?.status === 'active'` — correct but races async fetch |
| `frontend/src/middleware.ts` | 63 | Correct — role-based route guard |
| `frontend/next.config.ts` | 50 | COEP `credentialless` correct for WASM; no `/socket.io` proxy (direct connect) |
| `backend/main.py` | 61 | Socket.IO CORS `'*'` ✓; FastAPI CORS from `settings.cors_origins` |
| `backend/config.py` | 53 | Default CORS origin `["http://localhost:3000"]` |
| `backend/websocket/handlers.py` | 187 | No `session_ended` broadcast; `candidate_heartbeat` broadcasts to session room |
| `backend/routers/events.py` | 265 (partial) | Correct event persist + background Gemini + socket emit |
| `backend/auth/jwt_validator.py` | 95 | Role extracted from `user_metadata`/`app_metadata`; fails if neither set |
| `backend/auth/dependencies.py` | 39 | Correct role-check Depends |
| `frontend/public/models/` | — | **`coco_ssd/` directory MISSING** — only MediaPipe WASM files present |

---

## Conclusion

The app architecture is sound. All four live failures trace to **five concrete bugs**, none requiring redesign:

1. **Missing COCO-SSD model files** — objects always show `Loading`
2. **Stale closure in frame loop** — face analysis never fires after model loads  
3. **No `session_ended` broadcast/listener** — proctor can't terminate candidate
4. **Supabase session null fallback** — heartbeat/proctor connect silently skips on expired token
5. **Score decay drops to 0 instantly** instead of smooth 1.5 pts/sec decay

Fix P0 items first (model files + stale closure) — these alone will restore face analysis, risk scoring, and object detection, which are the primary demo-critical features.
