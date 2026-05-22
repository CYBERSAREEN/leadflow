const { Client, LocalAuth, RemoteAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const axios = require('axios');
const { handleIncomingMessage } = require('./message_handler');

const app = express();
app.use(express.json());

const FASTAPI_URL = 'http://localhost:8000';
const PORT = 3001;

let isReady = false;
let currentQR = null;

// Suppress unhandled rejections from whatsapp-web.js internal cache bugs
process.on('unhandledRejection', (reason) => {
  const msg = reason && reason.message ? reason.message : String(reason);
  if (msg.includes('LocalWebCache') || msg.includes('manifest') || msg.includes('null')) {
    console.warn('[WA] Suppressed internal cache error (non-fatal):', msg);
  } else {
    console.error('[WA] Unhandled rejection:', msg);
  }
});

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: './data/.wwebjs_auth' }),
  webVersionCache: {
    type: 'remote',
    remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/{version}.html',
  },
  puppeteer: {
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-accelerated-2d-canvas',
      '--no-first-run',
      '--no-zygote',
      '--single-process',
      '--disable-gpu'
    ],
    headless: true,
  },
});

client.on('qr', (qr) => {
  currentQR = qr;
  console.log('\n=== Scan this QR code with WhatsApp ===');
  qrcode.generate(qr, { small: true });
  console.log('=======================================\n');
});

client.on('authenticated', () => {
  console.log('WhatsApp authenticated successfully');
});

client.on('auth_failure', (msg) => {
  console.error('WhatsApp authentication failed:', msg);
});

client.on('ready', () => {
  isReady = true;
  currentQR = null;
  console.log('WhatsApp Connected ✓');
  console.log(`Connected as: ${client.info.wid.user}`);
});

client.on('disconnected', (reason) => {
  isReady = false;
  console.log('WhatsApp disconnected:', reason);
  console.log('Attempting to reconnect in 10 seconds...');
  setTimeout(() => {
    client.initialize().catch(err => {
      console.error('Reconnect failed:', err.message);
    });
  }, 10000);
});

client.on('message', async (message) => {
  if (message.fromMe) return;
  try {
    await handleIncomingMessage(message, FASTAPI_URL);
  } catch (err) {
    console.error('Error handling incoming message:', err.message);
  }
});

client.on('message_create', async (message) => {
  if (!message.fromMe) return;
});

app.post('/send', async (req, res) => {
  const { phone, message } = req.body;

  if (!phone || !message) {
    return res.status(400).json({ success: false, error: 'phone and message are required' });
  }

  if (!isReady) {
    return res.status(503).json({ success: false, error: 'WhatsApp client not ready' });
  }

  try {
    const chatId = phone.includes('@c.us') ? phone : `${phone}@c.us`;
    await client.sendMessage(chatId, message);
    res.json({ success: true });
  } catch (err) {
    console.error('Send message error:', err.message);
    res.status(500).json({ success: false, error: err.message });
  }
});

app.get('/status', (req, res) => {
  res.json({
    connected: isReady,
    phone: client.info ? client.info.wid.user : null,
  });
});

app.get('/qr', (req, res) => {
  res.json({ connected: isReady, qr: isReady ? null : currentQR });
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', ready: isReady });
});

app.post('/disconnect', async (req, res) => {
  try {
    await client.logout();
    isReady = false;
    currentQR = null;
    res.json({ success: true });
  } catch (err) {
    console.error('Disconnect error:', err.message);
    res.status(500).json({ success: false, error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`WhatsApp bridge server listening on port ${PORT}`);
});

client.initialize().catch(err => {
  console.error('WhatsApp client initialization error:', err.message);
});

process.on('SIGINT', async () => {
  console.log('Shutting down WhatsApp client...');
  try {
    await client.destroy();
  } catch (e) {}
  process.exit(0);
});
