const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const { handleIncomingMessage } = require('./message_handler');

const app = express();
app.use(express.json());

// CORS — allow any origin (needed for browser access)
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Bridge-Secret');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

const FASTAPI_URL = process.env.FASTAPI_URL || 'http://localhost:8000';
const PORT = parseInt(process.env.PORT || '3001', 10);
const BRIDGE_SECRET = process.env.BRIDGE_SECRET || 'leadflow-bridge-secret-2024';

let isReady = false;
let currentQR = null;
let reconnectAttempts = 0;
let reconnectTimer = null;

// ─── Rate Limiter ─────────────────────────────────────────────────────────────
// Allow max 1 outbound message per 1.5 seconds (WhatsApp rate limit safe zone)
const sendQueue = [];
let isSending = false;

async function processSendQueue() {
  if (isSending || sendQueue.length === 0) return;
  isSending = true;
  const { phone, message, resolve, reject } = sendQueue.shift();
  try {
    if (!isReady) throw new Error('WhatsApp client not ready');
    const chatId = phone.includes('@c.us') ? phone : `${phone}@c.us`;
    await client.sendMessage(chatId, message);
    resolve({ success: true });
  } catch (err) {
    reject(err);
  } finally {
    isSending = false;
    // Minimum 1.5s between sends to respect WA rate limits
    setTimeout(processSendQueue, 1500);
  }
}

function queueSend(phone, message) {
  return new Promise((resolve, reject) => {
    sendQueue.push({ phone, message, resolve, reject });
    processSendQueue();
  });
}

// ─── Suppress non-fatal internal WA errors ───────────────────────────────────
process.on('unhandledRejection', (reason) => {
  const msg = reason && reason.message ? reason.message : String(reason);
  const ignore = [
    'LocalWebCache', 'manifest', 'null', 'Target closed',
    'Session closed', 'Protocol error', 'Navigation failed',
  ];
  if (ignore.some(kw => msg.includes(kw))) {
    console.warn('[WA] Suppressed internal error (non-fatal):', msg.slice(0, 100));
  } else {
    console.error('[WA] Unhandled rejection:', msg);
  }
});

// ─── WhatsApp client ──────────────────────────────────────────────────────────
function createClient() {
  return new Client({
    authStrategy: new LocalAuth({ dataPath: './data/.wwebjs_auth' }),
    webVersionCache: {
      type: 'remote',
      remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/{version}.html',
    },
    puppeteer: {
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas',
        '--no-first-run',
        '--no-zygote',
        '--disable-gpu',
        '--disable-extensions',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-features=TranslateUI',
        '--window-size=1280,720',
        '--memory-pressure-off',
        '--max-old-space-size=512',
      ],
      headless: true,
      timeout: 90000,
    },
  });
}

let client = createClient();
registerClientEvents(client);

function registerClientEvents(c) {
  c.on('qr', (qr) => {
    currentQR = qr;
    console.log('\n=== Scan this QR code with WhatsApp ===');
    qrcode.generate(qr, { small: true });
    console.log('=======================================\n');
  });

  c.on('authenticated', () => {
    console.log('[WA] Authenticated successfully');
    reconnectAttempts = 0;
  });

  c.on('auth_failure', (msg) => {
    console.error('[WA] Auth failed:', msg);
    scheduleReconnect(5000);
  });

  c.on('ready', () => {
    isReady = true;
    currentQR = null;
    reconnectAttempts = 0;
    console.log('[WA] Connected ✓');
    if (c.info) console.log(`[WA] Logged in as: +${c.info.wid.user}`);
  });

  c.on('disconnected', (reason) => {
    isReady = false;
    console.log('[WA] Disconnected:', reason);
    scheduleReconnect(10000);
  });

  c.on('message', async (message) => {
    if (message.fromMe) return;
    try {
      await handleIncomingMessage(message, FASTAPI_URL, BRIDGE_SECRET);
    } catch (err) {
      console.error('[WA] Error handling incoming message:', err.message);
    }
  });
}

function scheduleReconnect(delay) {
  if (reconnectTimer) return; // already scheduled
  reconnectAttempts++;

  if (reconnectAttempts > 10) {
    const wait = Math.min(reconnectAttempts * 15000, 300000); // max 5 min
    console.log(`[WA] Reconnect attempt ${reconnectAttempts} — waiting ${wait / 1000}s...`);
    reconnectTimer = setTimeout(doReconnect, wait);
  } else {
    console.log(`[WA] Reconnect attempt ${reconnectAttempts} in ${delay / 1000}s...`);
    reconnectTimer = setTimeout(doReconnect, delay);
  }
}

async function doReconnect() {
  reconnectTimer = null;
  console.log('[WA] Attempting reconnect...');
  try {
    // Destroy old client and create fresh one
    try { await client.destroy(); } catch (e) {}
    client = createClient();
    registerClientEvents(client);
    await client.initialize();
    console.log('[WA] Reconnect initialize() called');
  } catch (err) {
    console.error('[WA] Reconnect failed:', err.message);
    scheduleReconnect(30000);
  }
}

// ─── HTTP API ─────────────────────────────────────────────────────────────────

app.post('/send', async (req, res) => {
  const { phone, message } = req.body;

  if (!phone || !message) {
    return res.status(400).json({ success: false, error: 'phone and message are required' });
  }

  if (!isReady) {
    return res.status(503).json({ success: false, error: 'WhatsApp client not ready — scan QR first' });
  }

  try {
    const result = await queueSend(phone, message);
    res.json(result);
  } catch (err) {
    console.error('[WA] Send error:', err.message);
    res.status(500).json({ success: false, error: err.message });
  }
});

app.get('/status', (req, res) => {
  const phone = client.info ? client.info.wid.user : null;
  res.json({
    connected: isReady || !!phone,
    phone,
    reconnectAttempts,
    queueLength: sendQueue.length,
  });
});

app.get('/qr', (req, res) => {
  res.json({ connected: isReady, qr: isReady ? null : currentQR });
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', ready: isReady, uptime: process.uptime() });
});

app.post('/disconnect', async (req, res) => {
  try {
    await client.logout();
    isReady = false;
    currentQR = null;
    res.json({ success: true });
  } catch (err) {
    console.error('[WA] Disconnect error:', err.message);
    res.status(500).json({ success: false, error: err.message });
  }
});

app.post('/restart', async (req, res) => {
  res.json({ success: true, message: 'Restarting...' });
  setTimeout(async () => {
    reconnectAttempts = 0;
    await doReconnect();
  }, 500);
});

// ─── Start ────────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`[WA] Bridge server listening on port ${PORT}`);
  console.log(`[WA] FastAPI URL: ${FASTAPI_URL}`);
});

// Initialize with retry
async function initWithRetry(maxAttempts = 5) {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      console.log(`[WA] Initialize attempt ${attempt}/${maxAttempts}...`);
      await client.initialize();
      console.log('[WA] initialize() returned');
      return;
    } catch (err) {
      console.error(`[WA] Initialize attempt ${attempt} failed:`, err.message);
      if (attempt < maxAttempts) {
        const wait = attempt * 10000;
        console.log(`[WA] Retrying in ${wait / 1000}s...`);
        await new Promise(r => setTimeout(r, wait));
        // Create fresh client
        try { await client.destroy(); } catch (e) {}
        client = createClient();
        registerClientEvents(client);
      }
    }
  }
  console.error('[WA] All initialize attempts failed — server running but WA disconnected');
}

initWithRetry().catch(err => {
  console.error('[WA] Fatal init error:', err.message);
});

// ─── Graceful shutdown ────────────────────────────────────────────────────────
process.on('SIGINT', async () => {
  console.log('[WA] Shutting down...');
  try { await client.destroy(); } catch (e) {}
  process.exit(0);
});

process.on('SIGTERM', async () => {
  console.log('[WA] SIGTERM received...');
  try { await client.destroy(); } catch (e) {}
  process.exit(0);
});
