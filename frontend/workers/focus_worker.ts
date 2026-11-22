// FILE: workers/focus_worker.ts
// focus_worker.ts is NOT a true Web Worker.
// It runs on the main thread but is isolated as a class.
// Reason: document visibility API only works on main thread.

export interface FocusEvent {
  type: 'tab_switch' | 'fullscreen_exit' | 'copy_paste' | 'context_switch' | 'dev_tools';
  severity: 'low' | 'medium' | 'high';
  timestamp: number;
  detail?: string;
}

export type FocusEventCallback = (event: FocusEvent) => void;

export class FocusMonitor {
  private callbacks: Map<string, FocusEventCallback> = new Map();
  private sessionId: string = '';
  private isInitialized: boolean = false;

  // Bound handlers for cleanup
  private boundOnVisibilityChange: () => void;
  private boundOnBlur: () => void;
  private boundOnFullscreenChange: () => void;
  private boundOnCopy: (e: Event) => void;
  private boundOnPaste: (e: Event) => void;
  private boundOnContextMenu: (e: Event) => void;
  private boundOnKeyDown: (e: KeyboardEvent) => void;

  constructor() {
    this.boundOnVisibilityChange = this.onVisibilityChange.bind(this);
    this.boundOnBlur = this.onBlur.bind(this);
    this.boundOnFullscreenChange = this.onFullscreenChange.bind(this);
    this.boundOnCopy = this.onCopy.bind(this);
    this.boundOnPaste = this.onPaste.bind(this);
    this.boundOnContextMenu = this.onContextMenu.bind(this);
    this.boundOnKeyDown = this.onKeyDown.bind(this);
  }

  init(sessionId: string): void {
    if (this.isInitialized) return;
    this.sessionId = sessionId;

    document.addEventListener('visibilitychange', this.boundOnVisibilityChange);
    window.addEventListener('blur', this.boundOnBlur);
    document.addEventListener('fullscreenchange', this.boundOnFullscreenChange);
    document.addEventListener('copy', this.boundOnCopy);
    document.addEventListener('paste', this.boundOnPaste);
    document.addEventListener('contextmenu', this.boundOnContextMenu);
    document.addEventListener('keydown', this.boundOnKeyDown);

    this.isInitialized = true;
  }

  destroy(): void {
    document.removeEventListener('visibilitychange', this.boundOnVisibilityChange);
    window.removeEventListener('blur', this.boundOnBlur);
    document.removeEventListener('fullscreenchange', this.boundOnFullscreenChange);
    document.removeEventListener('copy', this.boundOnCopy);
    document.removeEventListener('paste', this.boundOnPaste);
    document.removeEventListener('contextmenu', this.boundOnContextMenu);
    document.removeEventListener('keydown', this.boundOnKeyDown);
    this.isInitialized = false;
  }

  on(eventType: string, callback: FocusEventCallback): void {
    this.callbacks.set(eventType, callback);
  }

  onAny(callback: FocusEventCallback): void {
    this.callbacks.set('*', callback);
  }

  private emit(event: FocusEvent): void {
    const specificCb = this.callbacks.get(event.type);
    if (specificCb) specificCb(event);
    const anyCb = this.callbacks.get('*');
    if (anyCb) anyCb(event);
  }

  private onVisibilityChange(): void {
    if (document.hidden) {
      this.emit({
        type: 'tab_switch',
        severity: 'high',
        timestamp: Date.now(),
        detail: 'Tab became hidden',
      });
    }
  }

  private onBlur(): void {
    this.emit({
      type: 'context_switch',
      severity: 'medium',
      timestamp: Date.now(),
      detail: 'Window lost focus',
    });
  }

  private onFullscreenChange(): void {
    if (!document.fullscreenElement) {
      this.emit({
        type: 'fullscreen_exit',
        severity: 'high',
        timestamp: Date.now(),
        detail: 'Exited fullscreen mode',
      });
    }
  }

  private onCopy(e: Event): void {
    e.preventDefault();
    this.emit({
      type: 'copy_paste',
      severity: 'medium',
      timestamp: Date.now(),
      detail: 'Copy attempt blocked',
    });
  }

  private onPaste(e: Event): void {
    e.preventDefault();
    this.emit({
      type: 'copy_paste',
      severity: 'medium',
      timestamp: Date.now(),
      detail: 'Paste attempt blocked',
    });
  }

  private onContextMenu(e: Event): void {
    e.preventDefault();
    this.emit({
      type: 'context_switch',
      severity: 'low',
      timestamp: Date.now(),
      detail: 'Right-click blocked',
    });
  }

  private onKeyDown(e: KeyboardEvent): void {
    // Block F12 (dev tools)
    if (e.key === 'F12') {
      e.preventDefault();
      this.emit({
        type: 'dev_tools',
        severity: 'high',
        timestamp: Date.now(),
        detail: 'F12 key blocked',
      });
    }
    // Block Ctrl+U (view source)
    if (e.ctrlKey && e.key === 'u') {
      e.preventDefault();
      this.emit({
        type: 'dev_tools',
        severity: 'high',
        timestamp: Date.now(),
        detail: 'Ctrl+U blocked',
      });
    }
    // Block Ctrl+Shift+I (dev tools)
    if (e.ctrlKey && e.shiftKey && e.key === 'I') {
      e.preventDefault();
      this.emit({
        type: 'dev_tools',
        severity: 'high',
        timestamp: Date.now(),
        detail: 'Ctrl+Shift+I blocked',
      });
    }
  }
}

export default FocusMonitor;
