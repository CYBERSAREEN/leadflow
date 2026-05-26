const axios = require('axios');

// Rate limiter for inbound processing (avoid hammering FastAPI)
let lastProcessed = 0;
const MIN_INTERVAL_MS = 500; // min 500ms between API calls

async function handleIncomingMessage(message, fastapiUrl, bridgeSecret) {
  const rawFrom = message.from || '';

  // Skip group messages
  if (rawFrom.includes('@g.us')) return;
  // Skip status broadcasts
  if (rawFrom === 'status@broadcast') return;
  // Skip if no body
  if (!message.body && !message.caption) return;

  // Normalize phone — strip @c.us, spaces, dashes, leading +
  const phone = rawFrom
    .replace('@c.us', '')
    .replace('+', '')
    .replace(/[\s\-]/g, '')
    .trim();

  if (!phone) return;

  const body = message.body || message.caption || '';

  // Rate limit
  const now = Date.now();
  const elapsed = now - lastProcessed;
  if (elapsed < MIN_INTERVAL_MS) {
    await new Promise(r => setTimeout(r, MIN_INTERVAL_MS - elapsed));
  }
  lastProcessed = Date.now();

  // Get notify name (WhatsApp display name of the sender)
  let notifyName = null;
  try {
    notifyName = message.notifyName || message._data?.notifyName || null;
  } catch (e) {}

  const payload = {
    phone,
    body,
    wa_message_id: message.id ? message.id.id : null,
    timestamp: message.timestamp || Math.floor(Date.now() / 1000),
    notify_name: notifyName,
  };

  const headers = {
    'Content-Type': 'application/json',
  };
  if (bridgeSecret) {
    headers['X-Bridge-Secret'] = bridgeSecret;
  }

  try {
    const response = await axios.post(
      `${fastapiUrl}/api/messages/inbound`,
      payload,
      { timeout: 10000, headers }
    );
    console.log(`[MSG] From +${phone} (${notifyName || 'unknown'}) → lead_id: ${response.data.lead_id}`);
  } catch (err) {
    if (err.response) {
      console.error(`[MSG] FastAPI ${err.response.status}: ${JSON.stringify(err.response.data)}`);
    } else if (err.code === 'ECONNREFUSED') {
      console.error(`[MSG] FastAPI not reachable at ${fastapiUrl} — retrying in 5s`);
      // Retry once after 5s
      await new Promise(r => setTimeout(r, 5000));
      try {
        await axios.post(`${fastapiUrl}/api/messages/inbound`, payload, { timeout: 10000, headers });
        console.log(`[MSG] Retry succeeded for +${phone}`);
      } catch (retryErr) {
        console.error(`[MSG] Retry also failed: ${retryErr.message}`);
      }
    } else {
      console.error(`[MSG] Error: ${err.message}`);
    }
  }
}

module.exports = { handleIncomingMessage };
