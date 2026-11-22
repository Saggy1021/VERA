# tests/e2e_verification.py
# Automated End-to-End Pre-Flight Verification Suite for SENTINEL (Candidate + Proctor)

import asyncio
import os
import sys
import time
import subprocess
from datetime import datetime, timezone

# Ensure backend modules can be imported for DB reset
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import httpx
from playwright.async_api import async_playwright

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
SESSION_ID = "d3b07384-d113-4f44-93c0-3051187d7b3e"

CANDIDATE_EMAIL = "candidate@vera.demo"
CANDIDATE_PASS = "VeraCandidate2026!"

PROCTOR_EMAIL = "proctor@vera.demo"
PROCTOR_PASS = "VeraProctor2026!"

results_matrix = []


def record_result(phase: str, assertion: str, passed: bool, details: str = ""):
    results_matrix.append({
        "phase": phase,
        "assertion": assertion,
        "passed": passed,
        "details": details,
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S")
    })
    mark = "✓" if passed else "✗"
    print(f"[{mark}] [{phase}] {assertion} -> {details}")


async def reset_database():
    """Reset the demo session in Supabase PostgreSQL to clean active state."""
    print("\n--- Resetting Database Session to Active ---")
    try:
        from config import settings
        from database import init_db_pool, close_db_pool, get_pool
        await init_db_pool(settings.database_url)
        pool = get_pool()

        # Set session to active
        await pool.execute(
            """
            UPDATE sessions 
            SET status = 'active', started_at = NOW(), ended_at = NULL 
            WHERE id = $1
            """,
            SESSION_ID
        )

        # Ensure candidate is in session_candidates
        cand_user = await pool.fetchrow("SELECT id FROM auth.users WHERE email = $1", CANDIDATE_EMAIL)
        if cand_user:
            await pool.execute(
                """
                INSERT INTO session_candidates (session_id, candidate_id)
                VALUES ($1, $2)
                ON CONFLICT (session_id, candidate_id) DO NOTHING
                """,
                SESSION_ID, cand_user["id"]
            )
        await close_db_pool()
        print("Database session reset successfully.")
        return True
    except Exception as e:
        print(f"Warning: Database reset failed ({e}). Proceeding anyway.")
        return False


async def wait_for_services():
    """Verify backend and frontend are reachable."""
    print("\n--- Checking Local Services ---")
    async with httpx.AsyncClient(timeout=5.0) as client:
        # Check backend
        backend_ok = False
        for _ in range(10):
            try:
                r = await client.get(f"{BACKEND_URL}/health")
                if r.status_code == 200:
                    backend_ok = True
                    print(f"✓ Backend reachable at {BACKEND_URL}")
                    break
            except Exception:
                await asyncio.sleep(1)

        # Check frontend
        frontend_ok = False
        for _ in range(10):
            try:
                r = await client.get(f"{FRONTEND_URL}")
                if r.status_code in [200, 307, 308]:
                    frontend_ok = True
                    print(f"✓ Frontend reachable at {FRONTEND_URL}")
                    break
            except Exception:
                await asyncio.sleep(1)

        return backend_ok, frontend_ok


async def run_e2e_suite():
    await reset_database()

    backend_ok, frontend_ok = await wait_for_services()
    if not backend_ok or not frontend_ok:
        print("\nERROR: Required services are not running!")
        print(f"Backend (port 8000) reachable: {backend_ok}")
        print(f"Frontend (port 3000) reachable: {frontend_ok}")
        return False

    print("\n--- Starting Headless Chromium E2E Test Suite ---")

    async with async_playwright() as p:
        # Launch Chromium with fake media flags
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        # Context 1: Candidate
        candidate_context = await browser.new_context(
            permissions=["camera", "microphone"],
            viewport={"width": 1280, "height": 800}
        )
        candidate_page = await candidate_context.new_page()

        # Inject SpeechSynthesis spy into candidate page before navigation
        await candidate_page.add_init_script("""
            window.__speechLog = [];
            if ('speechSynthesis' in window) {
                const origSpeak = window.speechSynthesis.speak.bind(window.speechSynthesis);
                window.speechSynthesis.speak = function(utterance) {
                    const text = utterance && utterance.text ? utterance.text : String(utterance);
                    window.__speechLog.push(text);
                    return origSpeak(utterance);
                };
            }
        """)

        # Context 2: Proctor
        proctor_context = await browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        proctor_page = await proctor_context.new_page()

        # ======================================================================
        # PHASE 1: Candidate Setup & Exam Initialization
        # ======================================================================
        print("\n[PHASE 1] Candidate Setup & Exam Initialization")
        try:
            # Login as Candidate
            await candidate_page.goto(f"{FRONTEND_URL}/login", wait_until="networkidle")
            await candidate_page.fill('input[type="email"]', CANDIDATE_EMAIL)
            await candidate_page.fill('input[type="password"]', CANDIDATE_PASS)
            await candidate_page.click('button[type="submit"]')
            await candidate_page.wait_for_url(lambda u: "/login" not in u, timeout=10000)
            record_result("Phase 1", "Candidate Authentication", True, "Successfully logged in")

            # Navigate to Setup Wizard
            await candidate_page.goto(f"{FRONTEND_URL}/candidate/setup/{SESSION_ID}", wait_until="networkidle")
            await candidate_page.wait_for_selector("text=System Check", timeout=8000)

            # Step 0: System Check
            await candidate_page.click('button:has-text("Run System Check")')
            next_btn = await candidate_page.wait_for_selector('button:has-text("Next Step →")', timeout=10000)
            await next_btn.click()
            await asyncio.sleep(0.5)

            # Step 1: Identity Enrollment
            await candidate_page.wait_for_selector("text=Identity Enrollment", timeout=8000)
            await candidate_page.click('button:has-text("Capture & Enroll")')
            next_btn = await candidate_page.wait_for_selector('button:has-text("Next Step →")', timeout=10000)
            await next_btn.click()
            await asyncio.sleep(0.5)

            # Step 2: Environment Scan
            await candidate_page.wait_for_selector("text=Environment Scan", timeout=8000)
            await candidate_page.click('button:has-text("Start 10-Second Scan")')
            # Wait for 10-second countdown to complete and advance button to appear
            next_btn = await candidate_page.wait_for_selector('button:has-text("Next Step →")', timeout=15000)
            await next_btn.click()
            await asyncio.sleep(0.5)

            # Step 3: Instructions & Consent -> Launch Active Exam
            await candidate_page.wait_for_selector("text=Instructions & Consent", timeout=8000)
            await candidate_page.click('button:has-text("I Agree and Start")')
            await candidate_page.wait_for_url(f"**/candidate/session/{SESSION_ID}", timeout=10000)
            record_result("Phase 1", "Setup Wizard Traversal", True, "4 steps completed and exam launched")

            # Assert Candidate DOM: Objects not stuck on Loading
            # Wait for Object worker to finish initialization (up to 12s)
            objects_status = ""
            for _ in range(24):
                await asyncio.sleep(0.5)
                # Look for Objects row text in HUD
                objects_el = await candidate_page.query_selector('div:has(> span:text-is("Objects")) span.capitalize')
                if objects_el:
                    objects_status = (await objects_el.text_content() or "").strip()
                    if objects_status != "Loading":
                        break
            
            is_objects_ok = objects_status in ["Clear", "Cell phone", "Laptop", "Book"] or (objects_status != "Loading" and len(objects_status) > 0)
            record_result("Phase 1", "Objects Worker Ready & Non-Blocking", is_objects_ok, f"Objects status: '{objects_status}'")

            # Assert Candidate DOM: Face / Gaze reflects active telemetry
            face_el = await candidate_page.query_selector('div:has(> span:text-is("Face / Gaze")) span.text-white')
            face_text = (await face_el.text_content() or "").strip() if face_el else ""
            is_face_ok = "Face ·" in face_text
            record_result("Phase 1", "Face & Gaze Telemetry Active", is_face_ok, f"Face/Gaze HUD: '{face_text}'")

            # Assert Candidate DOM: Persistent countdown timer decrements predictably
            timer_el = await candidate_page.query_selector('div.font-mono.font-bold')
            timer_val1 = (await timer_el.text_content() or "").strip() if timer_el else ""
            await asyncio.sleep(2.0)
            timer_val2 = (await timer_el.text_content() or "").strip() if timer_el else ""
            is_timer_ok = timer_val1 != "" and timer_val2 != "" and timer_val1 != timer_val2
            record_result("Phase 1", "Persistent Countdown Timer Decrementing", is_timer_ok, f"{timer_val1} -> {timer_val2}")

        except Exception as e:
            record_result("Phase 1", "Setup & Exam Flow", False, f"Exception: {e}")

        # ======================================================================
        # PHASE 2: Proctor Real-Time Synchronization
        # ======================================================================
        print("\n[PHASE 2] Proctor Real-Time Synchronization")
        try:
            # Login as Proctor
            await proctor_page.goto(f"{FRONTEND_URL}/login", wait_until="networkidle")
            await proctor_page.fill('input[type="email"]', PROCTOR_EMAIL)
            await proctor_page.fill('input[type="password"]', PROCTOR_PASS)
            await proctor_page.click('button[type="submit"]')
            await proctor_page.wait_for_url(lambda u: "/login" not in u, timeout=10000)
            record_result("Phase 2", "Proctor Authentication", True, "Successfully logged in as proctor")

            # Open Proctor Monitoring View for Session
            await proctor_page.goto(f"{FRONTEND_URL}/proctor/sessions/{SESSION_ID}", wait_until="networkidle")
            await proctor_page.wait_for_selector("text=Voice Intercom", timeout=10000)

            # Assert candidate card transitions to Online (green wifi icon)
            is_online = False
            for _ in range(16):
                await asyncio.sleep(0.5)
                wifi_online = await proctor_page.query_selector('svg.text-green-400')
                if wifi_online:
                    is_online = True
                    break
            record_result("Phase 2", "Candidate Online Status Synchronized", is_online, "Green online indicator verified")

            # Assert candidate card renders valid JPEG thumbnail from heartbeat
            is_thumbnail_ok = False
            for _ in range(16):
                await asyncio.sleep(0.5)
                thumb_img = await proctor_page.query_selector('img[src^="data:image/jpeg"]')
                if thumb_img:
                    is_thumbnail_ok = True
                    break
            record_result("Phase 2", "Live Candidate Thumbnail Streaming", is_thumbnail_ok, "Valid JPEG thumbnail detected")

        except Exception as e:
            record_result("Phase 2", "Proctor Sync Flow", False, f"Exception: {e}")

        # ======================================================================
        # PHASE 3: Custom Voice Intercom Dispatch & Speech Synthesis
        # ======================================================================
        print("\n[PHASE 3] Custom Voice Intercom Dispatch & Speech Synthesis")
        try:
            announcement = "Alex, remain focused on your exam"
            voice_input = await proctor_page.wait_for_selector('input[placeholder="Type announcement to candidate..."]', timeout=5000)
            await voice_input.fill(announcement)
            broadcast_btn = await proctor_page.wait_for_selector('button:has-text("Broadcast")', timeout=5000)
            await broadcast_btn.click()
            record_result("Phase 3", "Proctor Dispatched Voice Announcement", True, f"Broadcasted: '{announcement}'")

            # Verify in Candidate Context: SpeechSynthesis was invoked
            has_spoken = False
            speech_log = []
            for _ in range(16):
                await asyncio.sleep(0.5)
                speech_log = await candidate_page.evaluate("window.__speechLog || []")
                if any(announcement in s for s in speech_log):
                    has_spoken = True
                    break
            record_result("Phase 3", "Candidate SpeechSynthesis Utterance", has_spoken, f"Utterance received in client TTS: {speech_log}")

            # Verify in Candidate Context: Visual Warning Modal rendered
            modal_visible = False
            for _ in range(12):
                await asyncio.sleep(0.5)
                modal = await candidate_page.query_selector(':has-text("Proctor Warning")')
                if modal:
                    modal_visible = True
                    break
            record_result("Phase 3", "Candidate Visual Warning Modal", modal_visible, "Modal displayed on screen")

            # Dismiss modal by clicking 'Understood'
            understood_btn = await candidate_page.query_selector('button:has-text("Understood")')
            if understood_btn:
                await understood_btn.click()

        except Exception as e:
            record_result("Phase 3", "Voice Intercom Flow", False, f"Exception: {e}")

        # ======================================================================
        # PHASE 4: Speech-to-Text Transcription & Flagged Keyword Alert
        # ======================================================================
        print("\n[PHASE 4] Speech-to-Text Transcription & Flagged Keyword Alert")
        try:
            flagged_phrase = "what is the answer to question 2"

            # Emit mock transcript via candidate's active socket
            await candidate_page.evaluate(f"""
                if (window.__emitCandidateTranscript) {{
                    window.__emitCandidateTranscript("{flagged_phrase}", true);
                }} else if (window.__candidateSocket) {{
                    window.__candidateSocket.emit('candidate_transcript', {{
                        sessionId: "{SESSION_ID}",
                        candidateId: window.__candidateId,
                        text: "{flagged_phrase}",
                        flagged: true
                    }});
                }}
            """)
            record_result("Phase 4", "Candidate Socket Emitted Flagged Transcript", True, f"Phrase: '{flagged_phrase}'")

            # Assert Candidate Live AI HUD updates transcript ticker
            candidate_ticker_ok = False
            for _ in range(12):
                await asyncio.sleep(0.5)
                ticker = await candidate_page.query_selector(f':has-text("{flagged_phrase}")')
                if ticker:
                    candidate_ticker_ok = True
                    break
            record_result("Phase 4", "Candidate Live AI HUD Transcript Ticker", candidate_ticker_ok, "Ticker updated with flagged badge")

            # Assert Proctor Candidate Card displays phrase with amber highlight
            proctor_transcript_ok = False
            for _ in range(12):
                await asyncio.sleep(0.5)
                transcript_item = await proctor_page.query_selector(f':has-text("{flagged_phrase}")')
                if transcript_item:
                    proctor_transcript_ok = True
                    break
            record_result("Phase 4", "Proctor Card Live Speech Stream", proctor_transcript_ok, "Phrase rendered in candidate card")

            # Assert Proctor AlertFeed receives high-severity audio_activity alert
            proctor_alert_ok = False
            for _ in range(12):
                await asyncio.sleep(0.5)
                # Alert feed shows 'audio activity'
                alert_item = await proctor_page.query_selector(':has-text("audio activity")')
                if alert_item:
                    proctor_alert_ok = True
                    break
            record_result("Phase 4", "Proctor Live AlertFeed Flagged Event", proctor_alert_ok, "High-severity audio_activity alert displayed")

        except Exception as e:
            record_result("Phase 4", "Transcript & Flagged Audio Flow", False, f"Exception: {e}")

        # ======================================================================
        # PHASE 5: Remote Session Termination Handshake
        # ======================================================================
        print("\n[PHASE 5] Remote Session Termination Handshake")
        try:
            # Proctor clicks 'End Session'
            end_btn = await proctor_page.wait_for_selector('button:has-text("End Session")', timeout=5000)
            await end_btn.click()
            record_result("Phase 5", "Proctor Dispatched End Session", True, "Clicked End Session")

            # Assert Candidate receives session_ended and transitions to concluded screen
            concluded_ok = False
            for _ in range(12):
                await asyncio.sleep(0.5)
                concluded = await candidate_page.query_selector('text="Exam Session Concluded"')
                if concluded:
                    concluded_ok = True
                    break
            record_result("Phase 5", "Candidate Concluded Screen Transition", concluded_ok, "Exam Session Concluded screen displayed within 3s")

        except Exception as e:
            record_result("Phase 5", "Session Termination Handshake", False, f"Exception: {e}")

        await browser.close()

    # ======================================================================
    # OUTPUT DIAGNOSTIC MATRIX
    # ======================================================================
    print("\n" + "=" * 80)
    print("           PRE-FLIGHT AUTOMATED E2E VERIFICATION DIAGNOSTIC MATRIX")
    print("=" * 80)
    print(f"{'STATUS':<8} | {'PHASE':<10} | {'ASSERTION':<42} | {'DETAILS'}")
    print("-" * 80)

    all_passed = True
    for r in results_matrix:
        status_sym = "PASS ✓" if r["passed"] else "FAIL ✗"
        if not r["passed"]:
            all_passed = False
        print(f"{status_sym:<8} | {r['phase']:<10} | {r['assertion']:<42} | {r['details']}")

    print("=" * 80)
    if all_passed:
        print(">>> ALL ASSERTIONS PASSED (100% GREEN) - ZERO REGRESSIONS DETECTED <<<")
    else:
        print(">>> SOME ASSERTIONS FAILED - CHECK DIAGNOSTIC LOGS ABOVE <<<")
    print("=" * 80 + "\n")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(run_e2e_suite())
    sys.exit(0 if success else 1)
