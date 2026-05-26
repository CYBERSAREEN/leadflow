/**
 * Handles incoming Baileys messages and forwards to FastAPI.
 */
const axios = require('axios');

let lastProcessed = 0;
const MIN_INTERVAL_MS = 500;

async function handleIncomingMessage(message, fastapiUrl, bridgeSecret) {
  const jid = message.key?.remoteJid || '';

  // Skip groups, broadcasts, status
  if (!jid || jid.endsWith('@g.us') || jid === 'status@broadcast') return;

  // Normalize phone — strip @s.whatsapp.net and non-digits
  const phone = jid.replace('@s.whatsapp.net', '').replace('+', '').trim();
  if (!phone) return;

  // Extract message body from all possible Baileys message types
  const m = message.message || {};
  const body = (
    m.conversation                                    ||
    m.extendedTextMessage?.text                       ||
    m.imageMessage?.caption                           ||
    m.videoMessage?.caption                           ||
    m.documentMessage?.caption                        ||
    m.buttonsResponseMessage?.selectedDisplayText     ||
    m.templateButtonReplyMessage?.selectedDisplayText ||
    m.listResponseMessage?.singleSelectReply?.selectedRowId ||
    m.interactiveResponseMessage?.nativeFlowResponseMessage?.paramsJson ||
    ''
  ).trim();

  if (!body) return; // skip empty/media-only messages

  // Rate limit
  const now = Date.now();
  const elapsed = now - lastProcessed;
  if (elapsed < MIN_INTERVAL_MS) {
    await new Promise(r => setTimeout(r, MIN_INTERVAL_MS - elapsed));
  }
  lastProcessed = Date.now();

  // Get sender display name (pushName = WhatsApp display name)
  const notifyName = message.pushName || null;

  const payload = {
    phone,
    body,
    wa_message_id: message.key?.id || null,
    timestamp: message.messageTimestamp
      ? Number(message.messageTimestamp)
      : Math.floor(Date.now() / 1000),
    notify_name: notifyName,
  };

  const headers = { 'Content-Type': 'application/json' };
  if (bridgeSecret) headers['X-Bridge-Secret'] = bridgeSecret;

  try {
    const response = await axios.post(
      `${fastapiUrl}/api/messages/inbound`,
      payload,
      { timeout: 10000, headers }
    );
    console.log(`[MSG] +${phone} (${notifyName || 'unknown'}) → lead_id:${response.data.lead_id}`);
  } catch (err) {
    if (err.response) {
      console.error(`[MSG] FastAPI ${err.response.status}:`, JSON.stringify(err.response.data));
    } else if (err.code === 'ECONNREFUSED') {
      console.error(`[MSG] FastAPI not reachable — retrying in 5s`);
      await new Promise(r => setTimeout(r, 5000));
      try {
        await axios.post(`${fastapiUrl}/api/messages/inbound`, payload, { timeout: 10000, headers });
        console.log(`[MSG] Retry OK for +${phone}`);
      } catch (e2) {
        console.error(`[MSG] Retry failed: ${e2.message}`);
      }
    } else {
      console.error(`[MSG] Error: ${err.message}`);
    }
  }
}

module.exports = { handleIncomingMessage };
