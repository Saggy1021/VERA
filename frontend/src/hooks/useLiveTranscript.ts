// FILE: src/hooks/useLiveTranscript.ts
// Native Web Speech API Live Transcription & Keyword Flagging

'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

export const SUSPICIOUS_KEYWORDS = [
  'answer',
  'question',
  'option a',
  'option b',
  'option c',
  'option d',
  'google',
  'chatgpt',
  'help',
  'solve',
  'repeat',
  'cheat',
] as const;

export interface UseLiveTranscriptOptions {
  lang?: string;
  continuous?: boolean;
  interimResults?: boolean;
  onSettledPhrase?: (text: string, flaggedKeyword: string | null) => void;
  onInterimPhrase?: (text: string) => void;
}

export function useLiveTranscript(options: UseLiveTranscriptOptions = {}) {
  const {
    lang = 'en-US',
    continuous = true,
    interimResults = true,
    onSettledPhrase,
    onInterimPhrase,
  } = options;

  const [transcript, setTranscript] = useState<string>('');
  const [interimText, setInterimText] = useState<string>('');
  const [lastFlaggedPhrase, setLastFlaggedPhrase] = useState<string | null>(null);
  const [isListening, setIsListening] = useState<boolean>(false);
  const [isSupported, setIsSupported] = useState<boolean>(false);

  const recognitionRef = useRef<any>(null);
  const shouldListenRef = useRef<boolean>(false);
  const onSettledRef = useRef(onSettledPhrase);
  const onInterimRef = useRef(onInterimPhrase);

  useEffect(() => {
    onSettledRef.current = onSettledPhrase;
  }, [onSettledPhrase]);

  useEffect(() => {
    onInterimRef.current = onInterimPhrase;
  }, [onInterimPhrase]);

  // Check keyword match in a string
  const checkKeywords = useCallback((text: string): string | null => {
    const lower = text.toLowerCase();
    for (const kw of SUSPICIOUS_KEYWORDS) {
      if (lower.includes(kw)) {
        return kw;
      }
    }
    return null;
  }, []);

  // Initialize SpeechRecognition instance
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const SpeechRecognitionAPI =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

    if (!SpeechRecognitionAPI) {
      console.warn('[useLiveTranscript] Web Speech API is not supported in this browser.');
      setIsSupported(false);
      return;
    }

    setIsSupported(true);
    const recognition = new SpeechRecognitionAPI();
    recognition.continuous = continuous;
    recognition.interimResults = interimResults;
    recognition.lang = lang;

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognition.onresult = (event: any) => {
      let currentInterim = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const item = event.results[i];
        const phrase = item[0]?.transcript?.trim() || '';
        if (item.isFinal) {
          if (phrase) {
            const matched = checkKeywords(phrase);
            setTranscript((prev) => (prev ? `${prev} ${phrase}` : phrase));
            setInterimText('');
            if (matched) {
              setLastFlaggedPhrase(matched);
            }
            onSettledRef.current?.(phrase, matched);
          }
        } else {
          currentInterim += ` ${phrase}`;
        }
      }

      const trimmedInterim = currentInterim.trim();
      if (trimmedInterim) {
        setInterimText(trimmedInterim);
        onInterimRef.current?.(trimmedInterim);
      }
    };

    recognition.onerror = (event: any) => {
      // Ignore normal silence/no-speech errors without interrupting state
      if (event.error === 'no-speech') {
        return;
      }
      if (event.error === 'aborted') {
        return;
      }
      console.warn('[useLiveTranscript] Recognition error:', event.error);
    };

    recognition.onend = () => {
      setIsListening(false);
      // Automatically restart if session is still meant to be listening
      if (shouldListenRef.current) {
        try {
          recognition.start();
        } catch {
          // Ignore restart collisions
        }
      }
    };

    recognitionRef.current = recognition;

    return () => {
      shouldListenRef.current = false;
      try {
        recognition.stop();
      } catch {}
      recognitionRef.current = null;
    };
  }, [lang, continuous, interimResults, checkKeywords]);

  const startListening = useCallback(() => {
    shouldListenRef.current = true;
    if (recognitionRef.current) {
      try {
        recognitionRef.current.start();
      } catch (err: any) {
        // Recognition might already be running
        if (err?.name !== 'InvalidStateError') {
          console.warn('[useLiveTranscript] Start error:', err);
        }
      }
    }
  }, []);

  const stopListening = useCallback(() => {
    shouldListenRef.current = false;
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
    }
    setIsListening(false);
  }, []);

  return {
    transcript,
    interimText,
    lastFlaggedPhrase,
    isListening,
    isSupported,
    startListening,
    stopListening,
  };
}
