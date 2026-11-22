// tests/e2e_verification.spec.ts
// Playwright TypeScript End-to-End Test Suite for SENTINEL Live Exam & Proctoring

import { test, expect, chromium } from '@playwright/test';

const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:3000';
const SESSION_ID = 'd3b07384-d113-4f44-93c0-3051187d7b3e';

const CANDIDATE_EMAIL = 'candidate@vera.demo';
const CANDIDATE_PASS = 'VeraCandidate2026!';

const PROCTOR_EMAIL = 'proctor@vera.demo';
const PROCTOR_PASS = 'VeraProctor2026!';

test.describe('SENTINEL Full Pre-Flight Proctor & Candidate E2E Suite', () => {
  test('Two-context real-time proctoring and voice intercom verification', async () => {
    // 1. Launch browser with fake media stream flags
    const browser = await chromium.launch({
      args: [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream',
        '--no-sandbox',
        '--disable-dev-shm-usage',
      ],
    });

    // 2. Candidate Context
    const candidateContext = await browser.new_context({
      permissions: ['camera', 'microphone'],
      viewport: { width: 1280, height: 800 },
    });
    const candidatePage = await candidateContext.new_page();

    // Inject SpeechSynthesis spy
    await candidatePage.addInitScript(() => {
      (window as any).__speechLog = [];
      if ('speechSynthesis' in window) {
        const origSpeak = window.speechSynthesis.speak.bind(window.speechSynthesis);
        window.speechSynthesis.speak = function (utterance: any) {
          const text = utterance && utterance.text ? utterance.text : String(utterance);
          (window as any).__speechLog.push(text);
          return origSpeak(utterance);
        };
      }
    });

    // 3. Proctor Context
    const proctorContext = await browser.new_context({
      viewport: { width: 1440, height: 900 },
    });
    const proctorPage = await proctorContext.new_page();

    // ─────────────────────────────────────────────────────────────
    // Phase 1: Candidate Setup & Exam Initialization
    // ─────────────────────────────────────────────────────────────
    // Candidate Login
    await candidatePage.goto(`${FRONTEND_URL}/login`);
    await candidatePage.fill('input[type="email"]', CANDIDATE_EMAIL);
    await candidatePage.fill('input[type="password"]', CANDIDATE_PASS);
    await candidatePage.click('button[type="submit"]');
    await candidatePage.waitForURL((url) => !url.pathname.includes('/login'));

    // Navigate to Setup Wizard
    await candidatePage.goto(`${FRONTEND_URL}/candidate/setup/${SESSION_ID}`);
    await candidatePage.waitForSelector('text=System Check');

    // Step 0: System Check
    await candidatePage.click('button:has-text("Run System Check")');
    const nextBtn0 = await candidatePage.waitForSelector('button:has-text("Next Step →")');
    await nextBtn0.click();

    // Step 1: Identity Enrollment
    await candidatePage.waitForSelector('text=Identity Enrollment');
    await candidatePage.click('button:has-text("Capture & Enroll")');
    const nextBtn1 = await candidatePage.waitForSelector('button:has-text("Next Step →")');
    await nextBtn1.click();

    // Step 2: Environment Scan
    await candidatePage.waitForSelector('text=Environment Scan');
    await candidatePage.click('button:has-text("Start 10-Second Scan")');
    const nextBtn2 = await candidatePage.waitForSelector('button:has-text("Next Step →")', { timeout: 15000 });
    await nextBtn2.click();

    // Step 3: Instructions & Consent -> Launch Active Exam
    await candidatePage.waitForSelector('text=Instructions & Consent');
    await candidatePage.click('button:has-text("I Agree and Start")');
    await candidatePage.waitForURL(`**/candidate/session/${SESSION_ID}`);

    // Assert: Objects not stuck on Loading
    const objectsEl = candidatePage.locator('div:has(> span:text-is("Objects")) span.capitalize');
    await expect(objectsEl).not.toHaveText('Loading', { timeout: 12000 });

    // Assert: Face / Gaze reflects active telemetry
    const faceEl = candidatePage.locator('div:has(> span:text-is("Face / Gaze")) span.text-white');
    await expect(faceEl).toContainText('Face ·', { timeout: 8000 });

    // Assert: Persistent countdown timer decrements predictably
    const timerEl = candidatePage.locator('div.font-mono.font-bold').first();
    const t1 = await timerEl.textContent();
    await candidatePage.waitForTimeout(2000);
    const t2 = await timerEl.textContent();
    expect(t1).not.toBe(t2);

    // ─────────────────────────────────────────────────────────────
    // Phase 2: Proctor Real-Time Synchronization
    // ─────────────────────────────────────────────────────────────
    // Proctor Login
    await proctorPage.goto(`${FRONTEND_URL}/login`);
    await proctorPage.fill('input[type="email"]', PROCTOR_EMAIL);
    await proctorPage.fill('input[type="password"]', PROCTOR_PASS);
    await proctorPage.click('button[type="submit"]');
    await proctorPage.waitForURL((url) => !url.pathname.includes('/login'));

    // Open Proctor Session
    await proctorPage.goto(`${FRONTEND_URL}/proctor/sessions/${SESSION_ID}`);
    await proctorPage.waitForSelector('text=Voice Intercom');

    // Assert Candidate Online Status (green indicator within 5s)
    const onlineIndicator = proctorPage.locator('svg.text-green-400').first();
    await expect(onlineIndicator).toBeVisible({ timeout: 8000 });

    // Assert JPEG Thumbnail Streaming
    const thumbnailImg = proctorPage.locator('img[src^="data:image/jpeg"]').first();
    await expect(thumbnailImg).toBeVisible({ timeout: 8000 });

    // ─────────────────────────────────────────────────────────────
    // Phase 3: Custom Voice Intercom Dispatch & Speech Synthesis
    // ─────────────────────────────────────────────────────────────
    const announcement = 'Alex, remain focused on your exam';
    const voiceInput = proctorPage.locator('input[placeholder="Type announcement to candidate..."]');
    await voiceInput.fill(announcement);
    await proctorPage.click('button:has-text("Broadcast")');

    // Candidate receives utterance in SpeechSynthesis
    await expect.poll(async () => {
      const logs = await candidatePage.evaluate(() => (window as any).__speechLog || []);
      return logs.some((l: string) => l.includes(announcement));
    }, { timeout: 8000 }).toBe(true);

    // Candidate receives visual warning modal
    const warningModal = candidatePage.locator(':has-text("Proctor Warning")').first();
    await expect(warningModal).toBeVisible({ timeout: 6000 });
    await candidatePage.click('button:has-text("Understood")');

    // ─────────────────────────────────────────────────────────────
    // Phase 4: Speech-to-Text Transcription & Flagged Keyword Alert
    // ─────────────────────────────────────────────────────────────
    const flaggedPhrase = 'what is the answer to question 2';
    await candidatePage.evaluate((phrase) => {
      if ((window as any).__emitCandidateTranscript) {
        (window as any).__emitCandidateTranscript(phrase, true);
      }
    }, flaggedPhrase);

    // Candidate Live AI HUD updates ticker
    const ticker = candidatePage.locator(`:has-text("${flaggedPhrase}")`).first();
    await expect(ticker).toBeVisible({ timeout: 6000 });

    // Proctor Candidate Card transcript list displays phrase
    const proctorTranscript = proctorPage.locator(`:has-text("${flaggedPhrase}")`).first();
    await expect(proctorTranscript).toBeVisible({ timeout: 6000 });

    // Proctor AlertFeed receives high-severity audio_activity alert
    const audioAlert = proctorPage.locator(':has-text("audio activity")').first();
    await expect(audioAlert).toBeVisible({ timeout: 6000 });

    // ─────────────────────────────────────────────────────────────
    // Phase 5: Remote Session Termination Handshake
    // ─────────────────────────────────────────────────────────────
    await proctorPage.click('button:has-text("End Session")');
    const concludedScreen = candidatePage.locator('text="Exam Session Concluded"');
    await expect(concludedScreen).toBeVisible({ timeout: 5000 });

    await browser.close();
  });
});
