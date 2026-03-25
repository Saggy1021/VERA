/**
 * VERA SessionManager
 * Manages client-side session state and WebSocket lifecycle.
 * Call SessionManager.init() on every page.
 * Call SessionManager.start(mode) when a session begins.
 * Call SessionManager.destroy() on disconnect / page unload.
 */

const SessionManager = (() => {
  const SESSION_KEY = 'vera_session';
  let _ws = null;
  let _sessionId = null;
  let _mode = null;
  let _onMessage = null;
  let _onFlag = null;
  let _reconnectTimer = null;
  const MAX_RECONNECT_ATTEMPTS = 3;
  let _reconnectAttempts = 0;

  function init() {
    window.addEventListener('beforeunload', destroy);
    window.addEventListener('visibilitychange', () => {
      if (document.hidden && _ws) {
        _sendEvent('TAB_SWITCH');
      }
    });
  }

  function start(mode, sessionId) {
    _mode = mode;
    _sessionId = sessionId || crypto.randomUUID();
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      id: _sessionId,
      mode: _mode,
      startedAt: Date.now()
    }));
    return _sessionId;
  }

  function connectWebSocket(url, options) {
    options = options || {};
    _onMessage = options.onMessage || null;
    _onFlag = options.onFlag || null;
    var onDisconnect = options.onDisconnect || null;

    _ws = new WebSocket(url);

    _ws.onopen = function() {
      console.log('[VERA] WebSocket connected. Session:', _sessionId);
      _reconnectAttempts = 0;
      _ws.send(JSON.stringify({
        type: 'SESSION_INIT',
        sessionId: _sessionId,
        mode: _mode
      }));
    };

    _ws.onmessage = function(event) {
      var data = JSON.parse(event.data);
      if (data.severity === 'HIGH' && _onFlag) {
        _onFlag(data);
      }
      if (_onMessage) _onMessage(data);
    };

    _ws.onclose = function() {
      if (_reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        _reconnectAttempts++;
        _reconnectTimer = setTimeout(function() {
          connectWebSocket(url, options);
        }, 2000 * _reconnectAttempts);
      } else if (onDisconnect) {
        onDisconnect();
      }
    };

    _ws.onerror = function(err) {
      console.error('[VERA] WebSocket error:', err);
    };

    return _ws;
  }

  function sendFrame(base64Frame) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ type: 'frame', data: base64Frame }));
    }
  }

  function sendAudio(base64Audio) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ type: 'audio_chunk', data: base64Audio }));
    }
  }

  function _sendEvent(eventType, payload) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      var msg = { type: 'EVENT', event: eventType };
      if (payload) {
        for (var k in payload) {
          if (payload.hasOwnProperty(k)) msg[k] = payload[k];
        }
      }
      _ws.send(JSON.stringify(msg));
    }
  }

  function sendSecurityFlags(flags) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify({ type: 'frame', data: '', security_flags: flags }));
    }
  }

  function destroy() {
    clearTimeout(_reconnectTimer);
    if (_ws) {
      _ws.onclose = null;   // Prevent reconnect on deliberate destroy
      _ws.close(1000, 'Session ended');
      _ws = null;
    }
    sessionStorage.removeItem(SESSION_KEY);
    _sessionId = null;
    _mode = null;
    _reconnectAttempts = 0;
  }

  function getSessionId() { return _sessionId; }
  function getMode() { return _mode; }

  return {
    init: init,
    start: start,
    connectWebSocket: connectWebSocket,
    sendFrame: sendFrame,
    sendAudio: sendAudio,
    sendSecurityFlags: sendSecurityFlags,
    destroy: destroy,
    getSessionId: getSessionId,
    getMode: getMode
  };
})();
