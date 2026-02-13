/* ═══════════════════════════════════════════════
   Scarlett Maid-Bot — Client Application
   ═══════════════════════════════════════════════ */

// ── State ───────────────────────────────────────
let currentMode = 'angel';
let isStreaming = false;
let hasMessages = false;

// ── DOM refs (let: reset may replace elements) ──
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
let charFace = document.getElementById('char-face');
let charGreeting = document.getElementById('char-greeting');
const memoryPanel = document.getElementById('memory-panel');
const drawerBackdrop = document.getElementById('drawer-backdrop');
const menuBtn = document.getElementById('menu-btn');
const drawerCloseBtn = document.getElementById('drawer-close-btn');

// ── Mobile: visualViewport keyboard handling ────
function setupViewportHandler() {
  if (!window.visualViewport) return;

  const app = document.querySelector('.app');

  function onViewportResize() {
    const h = window.visualViewport.height;
    document.documentElement.style.setProperty('--app-height', h + 'px');
    requestAnimationFrame(() => scrollToBottom());
  }

  function onViewportScroll() {
    // Prevent iOS viewport offset when keyboard opens
    window.scrollTo(0, 0);
  }

  window.visualViewport.addEventListener('resize', onViewportResize);
  window.visualViewport.addEventListener('scroll', onViewportScroll);
}

// ── Mobile: Memory Drawer ───────────────────────
function openDrawer() {
  memoryPanel.classList.add('open');
  drawerBackdrop.classList.add('open');
}

function closeDrawer() {
  memoryPanel.classList.remove('open');
  drawerBackdrop.classList.remove('open');
}

function setupDrawer() {
  menuBtn.addEventListener('click', openDrawer);
  drawerCloseBtn.addEventListener('click', closeDrawer);
  drawerBackdrop.addEventListener('click', closeDrawer);

  // Swipe-to-close
  let touchStartX = 0;
  let touchCurrentX = 0;
  let isSwiping = false;

  memoryPanel.addEventListener('touchstart', (e) => {
    touchStartX = e.touches[0].clientX;
    touchCurrentX = touchStartX;
    isSwiping = false;
  }, { passive: true });

  memoryPanel.addEventListener('touchmove', (e) => {
    touchCurrentX = e.touches[0].clientX;
    const diff = touchCurrentX - touchStartX;
    if (diff > 20) {
      isSwiping = true;
      memoryPanel.style.transform = `translateX(${diff}px)`;
      memoryPanel.style.transition = 'none';
    }
  }, { passive: true });

  memoryPanel.addEventListener('touchend', () => {
    memoryPanel.style.transition = '';
    if (isSwiping && touchCurrentX - touchStartX > 80) {
      closeDrawer();
    }
    memoryPanel.style.transform = '';
    isSwiping = false;
  }, { passive: true });
}

// ── iOS body-scroll prevention ──────────────────
function preventBodyScroll() {
  document.body.addEventListener('touchmove', (e) => {
    let target = e.target;
    while (target && target !== document.body) {
      if (target.classList.contains('chat-messages') ||
          target.classList.contains('memory-content')) {
        return; // allow scroll inside these containers
      }
      target = target.parentElement;
    }
    e.preventDefault();
  }, { passive: false });
}

// ── Scroll ──────────────────────────────────────
function scrollToBottom(smooth) {
  requestAnimationFrame(() => {
    chatMessages.scrollTo({
      top: chatMessages.scrollHeight,
      behavior: smooth ? 'smooth' : 'instant',
    });
  });
}

// ── Mode / Expression ───────────────────────────
function setMode(mode) {
  currentMode = mode;
  document.body.classList.toggle('psycho', mode === 'psycho');
  const chipMode = document.getElementById('chip-mode');
  chipMode.textContent = mode === 'psycho' ? 'PSYCHO' : 'ANGEL';
  chipMode.className = 'chip ' + (mode === 'psycho' ? 'mode-psycho' : 'mode-angel');
  charFace.classList.toggle('psycho', mode === 'psycho');
}

function setExpression(expression) {
  charFace.src = `/expressions/${expression}.png`;
  document.getElementById('expr-label').textContent = expression;
  document.getElementById('chip-expression').textContent = expression;
}

function shrinkGreeting() {
  if (!hasMessages) {
    hasMessages = true;
    const isDesktop = window.matchMedia('(min-width: 768px)').matches;
    charGreeting.style.padding = isDesktop ? '16px 0' : '8px 0';
    charFace.style.width = isDesktop ? '80px' : '60px';
    charFace.style.height = isDesktop ? '80px' : '60px';
    const charName = document.querySelector('.char-name');
    if (charName) charName.style.display = 'none';
  }
}

// ── TTS (sentence-split MP3 streaming + auto-play) ──
let currentAudio = null;
let _ttsAbort = null;

const SVG_PLAY = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
const SVG_STOP = '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>';
const SVG_LOADING = '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 0 1 10 10h-3a7 7 0 0 0-7-7V2z"/></svg>';

function splitBySentence(text) {
  const chunks = [];
  let current = '';
  for (let i = 0; i < text.length; i++) {
    current += text[i];
    if ('。！？!?\n'.includes(text[i])) {
      const trimmed = current.trim();
      if (trimmed) chunks.push(trimmed);
      current = '';
    }
  }
  const rest = current.trim();
  if (rest) chunks.push(rest);
  return chunks.length > 0 ? chunks : [text];
}

function stopTTS() {
  if (_ttsAbort) { _ttsAbort.abort(); _ttsAbort = null; }
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  document.querySelectorAll('.tts-btn.playing, .tts-btn.loading').forEach(b => {
    b.disabled = false;
    b.classList.remove('playing', 'loading');
    b.innerHTML = SVG_PLAY;
    b.title = 'Play';
    b.onclick = () => playTTS(b._ttsText, b);
  });
}

function resetTTSBtn(btn, text) {
  btn.disabled = false;
  btn.classList.remove('playing', 'loading');
  btn.innerHTML = SVG_PLAY;
  btn.title = 'Play';
  btn.onclick = () => playTTS(text, btn);
}

async function playTTS(text, btn) {
  stopTTS();

  const ac = new AbortController();
  _ttsAbort = ac;

  btn.disabled = true;
  btn.classList.add('loading');
  btn.innerHTML = SVG_LOADING;
  btn.title = 'Loading...';

  try {
    const chunks = splitBySentence(text);

    // Prefetch first sentence
    let nextResp = fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: chunks[0] }),
      signal: ac.signal,
    });

    for (let i = 0; i < chunks.length; i++) {
      if (ac.signal.aborted) break;

      const resp = await nextResp;
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `TTS failed (${resp.status})`);
      }

      // Prefetch next sentence while current one downloads/plays
      if (i + 1 < chunks.length) {
        nextResp = fetch('/api/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: chunks[i + 1] }),
          signal: ac.signal,
        });
      }

      const blob = await resp.blob();
      if (ac.signal.aborted) break;

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      currentAudio = audio;

      if (i === 0) {
        btn.disabled = false;
        btn.classList.remove('loading');
        btn.classList.add('playing');
        btn.innerHTML = SVG_STOP;
        btn.title = 'Stop';
        btn.onclick = () => stopTTS();
      }

      await new Promise((resolve) => {
        audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
        audio.onerror = () => { URL.revokeObjectURL(url); resolve(); };
        ac.signal.addEventListener('abort', () => { audio.pause(); URL.revokeObjectURL(url); resolve(); }, { once: true });
        audio.play().catch(() => { URL.revokeObjectURL(url); resolve(); });
      });
    }

    if (!ac.signal.aborted) {
      currentAudio = null;
      resetTTSBtn(btn, text);
    }
  } catch (e) {
    if (e.name !== 'AbortError') console.error('TTS error:', e);
    if (!ac.signal.aborted) resetTTSBtn(btn, text);
  }
}

function makeTTSButton(text) {
  const btn = document.createElement('button');
  btn.className = 'tts-btn';
  btn.innerHTML = SVG_PLAY;
  btn.title = 'Play';
  btn._ttsText = text;
  btn.onclick = () => playTTS(text, btn);
  return btn;
}

// ── Messages ────────────────────────────────────
function addMessage(role, content, mode) {
  shrinkGreeting();
  const div = document.createElement('div');
  const modeClass = role === 'assistant' ? (mode || currentMode) : '';
  div.className = `msg msg-${role}` + (modeClass ? ` ${modeClass}` : '');

  const header = document.createElement('div');
  header.className = 'msg-header';

  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = role === 'user' ? 'Master' : 'Scarlett';
  header.appendChild(label);

  if (role === 'assistant') {
    header.appendChild(makeTTSButton(content));
  }

  const body = document.createElement('div');
  body.className = 'msg-content';
  if (role === 'assistant') {
    body.innerHTML = marked.parse(content);
  } else {
    body.textContent = content;
  }

  div.appendChild(header);
  div.appendChild(body);
  chatMessages.appendChild(div);
  scrollToBottom();
  return body;
}

function createStreamingMessage() {
  shrinkGreeting();
  const div = document.createElement('div');
  div.className = `msg msg-assistant ${currentMode}`;
  div.id = 'streaming-msg';

  const header = document.createElement('div');
  header.className = 'msg-header';

  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = 'Scarlett';
  header.appendChild(label);

  const body = document.createElement('div');
  body.className = 'msg-content streaming-cursor';
  body.id = 'streaming-body';

  div.appendChild(header);
  div.appendChild(body);
  chatMessages.appendChild(div);
  scrollToBottom();
  return body;
}

// ── Tool UI helpers ─────────────────────────────
const TOOL_LABELS = {
  web_search: 'Web Search',
  fetch_url: 'Fetch URL',
  get_current_time: 'Current Time',
  calculate: 'Calculate',
  delete_calendar_event: 'Delete Event',
};

function getToolStatusContainer() {
  let container = document.getElementById('tool-status-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'tool-status';
    container.id = 'tool-status-container';
    chatMessages.appendChild(container);
    scrollToBottom();
  }
  return container;
}

function addToolStart(tool, callId) {
  const container = getToolStatusContainer();
  const item = document.createElement('div');
  item.className = 'tool-status-item running';
  item.id = `tool-${callId}`;
  const label = TOOL_LABELS[tool] || tool;
  item.innerHTML = `<span class="tool-icon"></span><span class="tool-name">${label}</span><span class="tool-detail">running...</span>`;
  container.appendChild(item);
  scrollToBottom();
}

function addToolDone(tool, callId, summary) {
  const item = document.getElementById(`tool-${callId}`);
  if (item) {
    item.classList.remove('running');
    item.classList.add('done');
    const short = summary && summary.length > 60 ? summary.slice(0, 60) + '...' : (summary || 'done');
    item.innerHTML = `<span class="tool-icon">&#10003;</span><span class="tool-name">${TOOL_LABELS[tool] || tool}</span><span class="tool-detail">${short}</span>`;
  }
}

function clearToolStatus() {
  const container = document.getElementById('tool-status-container');
  if (container) container.remove();
}

function showLLMRetryStatus(data) {
  const container = getToolStatusContainer();
  let item = document.getElementById('llm-retry-status');
  if (!item) {
    item = document.createElement('div');
    item.className = 'tool-status-item running';
    item.id = 'llm-retry-status';
    container.appendChild(item);
  }
  const attempt = data.attempt || 1;
  const maxRetries = data.max_retries || 5;
  const waitSeconds = Number(data.wait_seconds || 0).toFixed(1);
  item.innerHTML = `<span class="tool-icon"></span><span class="tool-name">Cerebras</span><span class="tool-detail">busy, retry ${attempt}/${maxRetries} in ${waitSeconds}s</span>`;
  scrollToBottom();
}

function clearLLMRetryStatus() {
  const item = document.getElementById('llm-retry-status');
  if (item) item.remove();
}

// ── Send Message (SSE streaming) ────────────────
async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text || isStreaming) return;

  chatInput.value = '';
  isStreaming = true;
  sendBtn.disabled = true;

  addMessage('user', text);

  let streamBody = null;
  let rawText = '';

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let currentEvent = 'message';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
          continue;
        }
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));

            if (currentEvent === 'tool_start') {
              addToolStart(data.tool, data.call_id);
            }

            else if (currentEvent === 'tool_done') {
              addToolDone(data.tool, data.call_id, data.summary);
            }

            else if (currentEvent === 'token') {
              if (!streamBody) {
                streamBody = createStreamingMessage();
              }
              clearLLMRetryStatus();
              rawText += data.token;
              streamBody.innerHTML = marked.parse(rawText);
              scrollToBottom();
            }

            else if (currentEvent === 'confirm_action') {
              showConfirmAction(data);
            }

            else if (currentEvent === 'llm_retry') {
              showLLMRetryStatus(data);
            }

            else if (currentEvent === 'done') {
              clearLLMRetryStatus();
              setMode(data.mode);
              setExpression(data.expression);
              if (streamBody) {
                streamBody.classList.remove('streaming-cursor');
              }
              const streamMsg = document.getElementById('streaming-msg');
              if (streamMsg) {
                streamMsg.className = `msg msg-assistant ${data.mode}`;
                streamMsg.removeAttribute('id');
                streamMsg.querySelector('.msg-label').className = 'msg-label';
                // Add TTS button and auto-play
                const hdr = streamMsg.querySelector('.msg-header');
                if (hdr && rawText) {
                  const ttsBtn = makeTTSButton(rawText);
                  hdr.appendChild(ttsBtn);
                  playTTS(rawText, ttsBtn);
                }
              }
              if (streamBody) {
                streamBody.innerHTML = marked.parse(rawText);
              }
            }

            else if (currentEvent === 'error') {
              clearLLMRetryStatus();
              if (!streamBody) streamBody = createStreamingMessage();
              streamBody.innerHTML = `<span style="color:var(--red)">Error: ${data.error}</span>`;
              streamBody.classList.remove('streaming-cursor');
            }

          } catch (e) {}
          currentEvent = 'message'; // reset after processing data line
        }
      }
    }
  } catch (err) {
    clearLLMRetryStatus();
    if (!streamBody) streamBody = createStreamingMessage();
    streamBody.innerHTML = `<span style="color:var(--red)">Connection error: ${err.message}</span>`;
    streamBody.classList.remove('streaming-cursor');
  }

  // Fallback: if stream ended without 'done' event, still add TTS button
  const streamMsg = document.getElementById('streaming-msg');
  if (streamMsg && rawText) {
    streamMsg.removeAttribute('id');
    if (streamBody) streamBody.classList.remove('streaming-cursor');
    const hdr = streamMsg.querySelector('.msg-header');
    if (hdr && !hdr.querySelector('.tts-btn')) {
      const ttsBtn = makeTTSButton(rawText);
      hdr.appendChild(ttsBtn);
      playTTS(rawText, ttsBtn);
    }
  }

  // Clean up tool status indicators
  clearLLMRetryStatus();
  clearToolStatus();

  isStreaming = false;
  sendBtn.disabled = false;
  chatInput.focus();
  refreshMemory();
}

// ── Memory ──────────────────────────────────────
async function refreshMemory() {
  try {
    const [statusResp, memResp] = await Promise.all([
      fetch('/api/status'),
      fetch('/api/memory'),
    ]);
    const status = await statusResp.json();
    const mem = await memResp.json();

    document.getElementById('chip-phase').textContent = `Phase ${status.phase}: ${status.phase_name}`;
    document.getElementById('chip-sessions').textContent = `${status.session_count} sessions`;
    document.getElementById('chip-model').textContent = status.model;

    const metaDiv = document.getElementById('mem-metadata');
    if (mem.metadata) {
      const d = mem.metadata;
      metaDiv.innerHTML = `
        <div class="mem-item"><span class="key">Master:</span> <span class="val">${d.master_name || '(unknown)'}</span></div>
        <div class="mem-item"><span class="key">Phase:</span> <span class="val">${d.relationship_phase}</span></div>
        <div class="mem-item"><span class="key">Sessions:</span> <span class="val">${d.session_count}</span></div>
        <div class="mem-item"><span class="key">Last:</span> <span class="val">${d.last_session ? new Date(d.last_session).toLocaleString() : '-'}</span></div>
      `;
    }

    const semDiv = document.getElementById('mem-semantic');
    if (mem.semantic && mem.semantic.length > 0) {
      semDiv.innerHTML = mem.semantic.filter(s => s).map(s => `<div class="mem-semantic-item">${s}</div>`).join('');
    } else {
      semDiv.innerHTML = '<div class="mem-item" style="color:var(--text-dim)">No memories yet</div>';
    }
  } catch (e) {
    console.error('Memory refresh error:', e);
  }
}

async function saveMemory() {
  await fetch('/api/memory/save', { method: 'POST' });
  refreshMemory();
}

async function resetMemory() {
  if (!confirm('Reset all memory? This cannot be undone.')) return;
  await fetch('/api/memory/reset', { method: 'POST' });
  // Reset chat
  chatMessages.innerHTML = '';
  hasMessages = false;
  chatMessages.innerHTML = `
    <div class="char-greeting" id="char-greeting">
      <img class="char-face" id="char-face" src="/expressions/smile.png" alt="Scarlett">
      <div class="char-name">Scarlett</div>
      <div class="char-expr" id="expr-label">smile</div>
    </div>`;
  // Re-query replaced elements
  charFace = document.getElementById('char-face');
  charGreeting = document.getElementById('char-greeting');
  setMode('angel');
  refreshMemory();
}

// ── Pending Action Confirmation UI ───────────────
function showConfirmAction(data) {
  const div = document.createElement('div');
  div.className = 'confirm-action';
  div.innerHTML = `
    <div class="confirm-msg">&#128197; 이벤트 삭제 확인</div>
    <div class="confirm-detail"><strong>${data.title || ''}</strong> (${data.time || ''})</div>
    <div class="confirm-buttons">
      <button class="confirm-btn confirm-yes">삭제</button>
      <button class="confirm-btn confirm-no">취소</button>
    </div>
  `;

  div.querySelector('.confirm-yes').onclick = async () => {
    const btns = div.querySelector('.confirm-buttons');
    btns.innerHTML = '<span class="confirm-loading">처리 중...</span>';
    try {
      const resp = await fetch(`/api/confirm-action/${data.action_id}`, { method: 'POST' });
      const result = await resp.json();
      if (result.status === 'completed') {
        div.innerHTML = `<div class="confirm-result confirm-done">&#10003; ${result.message}</div>`;
      } else {
        div.innerHTML = `<div class="confirm-result confirm-error">${result.message}</div>`;
      }
    } catch (e) {
      div.innerHTML = `<div class="confirm-result confirm-error">오류: ${e.message}</div>`;
    }
  };

  div.querySelector('.confirm-no').onclick = async () => {
    try {
      await fetch(`/api/cancel-action/${data.action_id}`, { method: 'POST' });
    } catch (e) {}
    div.innerHTML = '<div class="confirm-result confirm-cancelled">삭제가 취소되었습니다</div>';
  };

  chatMessages.appendChild(div);
  scrollToBottom();
}

// ── Event Listeners ─────────────────────────────
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

sendBtn.addEventListener('click', sendMessage);
document.getElementById('btn-save').addEventListener('click', saveMemory);
document.getElementById('btn-reset').addEventListener('click', resetMemory);

// ── Init ────────────────────────────────────────
setupViewportHandler();
setupDrawer();
preventBodyScroll();
refreshMemory();
chatInput.focus();
