const axios = require('axios');

async function handleIncomingMessage(message, fastapiUrl) {
  const phone = message.from.replace('@c.us', '').replace('@g.us', '');

  if (message.from.includes('@g.us')) {
    return;
  }

  const payload = {
    phone: phone,
    body: message.body || '',
    wa_message_id: message.id.id,
    timestamp: message.timestamp,
  };

  try {
    const response = await axios.post(
      `${fastapiUrl}/api/messages/inbound`,
      payload,
      { timeout: 8000 }
    );
    console.log(`Inbound message from ${phone} forwarded to FastAPI — lead_id: ${response.data.lead_id}`);
  } catch (err) {
    if (err.response) {
      console.error(`FastAPI error ${err.response.status}: ${JSON.stringify(err.response.data)}`);
    } else if (err.code === 'ECONNREFUSED') {
      console.error('FastAPI server not reachable at localhost:8000 — message not forwarded');
    } else {
      console.error(`handleIncomingMessage error: ${err.message}`);
    }
  }
}

module.exports = { handleIncomingMessage };
