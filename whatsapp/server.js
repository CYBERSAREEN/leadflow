/**
 * LeadFlow WhatsApp Bridge — powered by @whiskeysockets/baileys
 * Memory: ~80MB (vs 400-500MB with Puppeteer/Chromium)
 */

const {
  default: makeWASocket,
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  isJidBroadcast,
  isJidGroup,
} = require('@whiskeysockets/baileys');
const P = require('pino');
const express = require('express');
const { handleIncomingMessage } = require('./message_handler');

const app = express();
app.use(express.json());

app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Bridge-Secret');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

const FASTAPI_URL   = process.env.FASTAPI_URL   || 'http://localhost:8000';
const PORT          = parseInt(process.env.PORT  || '3001', 10);
const BRIDGE_SECRET = process.env.BRIDGE_SECRET  || 'leadflow-bridge-secret-2024';
const AUTH_FOLDER   = process.env.AUTH_FOLDER    || './data/baileys_auth';

let sock           = null;
let isReady        = false;
let currentQR      = null;
let phoneNumber    = null;
let reconnectTimer = null;
let reconnectCount = 0;

// ─── Rate Limiter ─────────────────────────────────────────────────────────────
const sendQueue = [];
let isSending = false;

async function processSendQueue() {
  if (isSending || sendQueue.length === 0) return;
  isSending = true;
  const { jid, message, resolve, reject } = sendQueue.shift();
  try {
    if (!sock || !isReady) throw new Error('WhatsApp not connected');
    await sock.sendMessage(jid, { text: message });
    resolve({ success: true });
  } catch (err) {
    reject(err);
  } finally {
    isSending = false;
    setTimeout(processSendQueue, 1500);
  }
}

function queueSend(phone, message) {
  return new Promise((resolve, reject) => {
    const clean = phone.replace(/[+\s\-]/g,'').replace(/@c\.us|@s\.whatsapp\.net/g,'');
    sendQueue.push({ jid: `${clean}@s.whatsapp.net`, message, resolve, reject });
    processSendQueue();
  });
}

// ─── Baileys Socket ───────────────────────────────────────────────────────────
async function startSocket() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  try {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_FOLDER);
    const { version } = await fetchLatestBaileysVersion();
    console.log(`[WA] Baileys ${version.join('.')} | auth: ${AUTH_FOLDER}`);

    sock = makeWASocket({
      version,
      auth: state,
      logger: P({ level: 'silent' }),
      printQRInTerminal: true,
      getMessage: async () => undefined,
      syncFullHistory: false,
      markOnlineOnConnect: false,
      generateHighQualityLinkPreview: false,
      fireInitQueries: false,
      emitOwnEvents: false,
      connectTimeoutMs: 60000,
      keepAliveIntervalMs: 25000,
      browser: ['LeadFlow CRM', 'Chrome', '124.0'],
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
      if (qr) {
        currentQR = qr;
        console.log('[WA] QR ready — scan with WhatsApp');
      }
      if (connection === 'open') {
        isReady = true;
        currentQR = null;
        reconnectCount = 0;
        phoneNumber = sock.user?.id?.split(':')[0] || null;
        console.log(`[WA] Connected as +${phoneNumber}`);
      }
      if (connection === 'close') {
        isReady = false;
        phoneNumber = null;
        const code = lastDisconnect?.error?.output?.statusCode;
        console.log(`[WA] Closed — code:${code} reason:${lastDisconnect?.error?.message}`);
        if (code === DisconnectReason.loggedOut) {
          console.log('[WA] Logged out — restart to re-link');
          currentQR = null;
          return;
        }
        reconnectCount++;
        const delay = Math.min(reconnectCount * 8000, 120000);
        console.log(`[WA] Reconnect #${reconnectCount} in ${delay/1000}s`);
        reconnectTimer = setTimeout(startSocket, delay);
      }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify') return;
      for (const msg of messages) {
        if (msg.key.fromMe) continue;
        const jid = msg.key.remoteJid || '';
        if (!jid || isJidGroup(jid) || isJidBroadcast(jid) || jid === 'status@broadcast') continue;
        try {
          await handleIncomingMessage(msg, FASTAPI_URL, BRIDGE_SECRET);
        } catch (err) {
          console.error('[WA] msg handler error:', err.message);
        }
      }
    });

  } catch (err) {
    console.error('[WA] startSocket error:', err.message);
    reconnectCount++;
    const delay = Math.min(reconnectCount * 10000, 120000);
    reconnectTimer = setTimeout(startSocket, delay);
  }
}

// ─── HTTP API ─────────────────────────────────────────────────────────────────
app.post('/send', async (req, res) => {
  const { phone, message } = req.body;
  if (!phone || !message) return res.status(400).json({ success: false, error: 'phone and message required' });
  if (!isReady) return res.status(503).json({ success: false, error: 'WhatsApp not connected' });
  try {
    res.json(await queueSend(phone, message));
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

app.get('/status', (req, res) => {
  res.json({ connected: isReady, phone: phoneNumber, queueLength: sendQueue.length });
});

app.get('/qr', (req, res) => {
  res.json({ connected: isReady, qr: isReady ? null : currentQR });
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', ready: isReady, memoryMB: Math.round(process.memoryUsage().rss/1024/1024) });
});

app.post('/disconnect', async (req, res) => {
  try {
    if (sock) { await sock.logout(); sock = null; }
    isReady = false; currentQR = null; phoneNumber = null;
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

app.post('/restart', (req, res) => {
  res.json({ success: true, message: 'Restarting...' });
  setTimeout(async () => {
    try { if (sock) { await sock.end(); sock = null; } } catch(e) {}
    isReady = false; reconnectCount = 0;
    startSocket();
  }, 300);
});

app.listen(PORT, () => {
  console.log(`[WA] Bridge on port ${PORT} | FastAPI: ${FASTAPI_URL}`);
});

startSocket();

process.on('SIGINT',  async () => { try { if(sock) await sock.end(); } catch(e){} process.exit(0); });
process.on('SIGTERM', async () => { try { if(sock) await sock.end(); } catch(e){} process.exit(0); });

process.on('unhandledRejection', (reason) => {
  const msg = String(reason?.message || reason);
  const ignore = ['Connection Closed','timed out','ECONNRESET','socket hang up','ENOTFOUND','Timed Out','stream errored'];
  if (ignore.some(k => msg.includes(k))) console.warn('[WA] Suppressed:', msg.slice(0,80));
  else console.error('[WA] Unhandled rejection:', msg);
});
