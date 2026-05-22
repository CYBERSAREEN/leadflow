# LeadFlow AI — User Manual

## Overview

LeadFlow AI is a WhatsApp-powered lead management system that automatically captures, tracks, and follows up with leads. This manual covers all day-to-day operations.

---

## Getting Started

### Starting the System

```bash
# Start everything (Python backend + WhatsApp bridge)
./start.sh
```

The dashboard will be available at **http://localhost:8000**

### Connecting WhatsApp

1. Open the dashboard in your browser
2. Click **"📱 Connect WhatsApp"** in the sidebar footer
3. A QR code will appear in the modal
4. On your phone: open WhatsApp → **Linked Devices** → **Link a Device**
5. Scan the QR code
6. The sidebar will show a green dot and your phone number once connected

> The QR code refreshes automatically every 20 seconds. If it expires, click **Refresh QR**.

---

## Dashboard

The dashboard gives a live overview of your pipeline:

| Widget | Description |
|--------|-------------|
| **Total Leads** | All leads in the system |
| **New Today** | Leads captured today |
| **Converted** | Successfully converted leads + conversion rate |
| **Messages Today** | WhatsApp messages sent & received today |
| **Automated Leads** | Most recent leads (auto-captured via WhatsApp highlighted) |
| **Pipeline Overview** | Bar chart of leads by stage |
| **Leads Over Time** | 30-day trend chart |
| **Follow-up Due** | Leads with follow-up dates that are due |

The dashboard auto-refreshes every 60 seconds.

---

## Managing Leads

### Adding a Lead Manually

1. Navigate to **Leads** in the sidebar
2. Click **+ Add Lead** (top right)
3. Enter Name, Phone (e.g. `917087603933`), and Source
4. Click **Add Lead**

> Phone numbers must include country code with no `+` (e.g. India: `91` + number)

### Viewing a Lead

Click any row in the Leads table to open the **Lead Detail Panel**:

- **Lead Info** — source, AI score, created date, last contacted
- **Update Lead** — change status, set follow-up date, add notes
- **Conversation** — full WhatsApp chat history
- **Send Message** — send a WhatsApp message or use AI-suggested reply

### Lead Statuses

| Status | Meaning |
|--------|---------|
| `new` | Just captured, not yet contacted |
| `contacted` | Initial message sent |
| `interested` | Lead has shown interest |
| `converted` | Successfully converted to customer |
| `lost` | No longer a viable lead |

### Setting a Follow-up Date

In the Lead Detail Panel → **Update Lead** section:
- Pick a date in the **Follow-up Date** field
- Click **Save**
- The lead will appear in the **Follow-up Due** table on the Dashboard when the date arrives

### Searching and Filtering

On the Leads page:
- Use the **status dropdown** to filter by lead stage
- Use the **search box** to find leads by name or phone number

---

## WhatsApp Messaging

### Automatic Lead Capture

When an unknown number messages your WhatsApp, LeadFlow automatically:
1. Creates a new lead with `source: whatsapp`
2. Stores the message
3. Shows a toast notification in the dashboard

### Sending a Message

1. Open a lead's detail panel
2. Type in the **Send Message** box
3. Click **Send via WhatsApp**

### AI Reply Suggestions

1. Open a lead's detail panel
2. Click **✨ Suggest Reply**
3. The AI generates a context-aware reply based on the conversation
4. Click **Use This** to populate the message box, then **Send**

---

## AI Insights & Scoring

### Scoring a Single Lead

On the Leads page, click **Score** next to any lead. The AI will analyse the conversation and return a score 0–100 with an intent level.

### Scoring All Leads

1. Go to **AI Insights**
2. Click **⚡ Score All Leads**
3. A progress bar shows scoring status in real time

### Generating Daily Insights

1. Go to **AI Insights**
2. Click **🤖 Generate Today's Insights**
3. The AI analyses all leads and generates a written summary with recommendations

---

## Reports

Reports are auto-generated every day at **8:00 AM** and show:
- Total, new, contacted, and converted lead counts
- AI-written insights for the day

To export all leads as a CSV file: go to **Reports** and click **⬇ Download Leads CSV**.

---

## Deploying to Vercel

1. Deploy the Python backend to a persistent host (Railway, Render, Fly.io):
   ```bash
   # Example: Railway
   railway up
   ```

2. Set the backend URL in `vercel.json`:
   ```json
   { "env": { "LEADFLOW_BACKEND_URL": "https://your-app.railway.app" } }
   ```

3. Add the backend URL as a Vercel environment variable:
   ```
   LEADFLOW_BACKEND_URL = https://your-app.railway.app
   ```

4. Deploy the frontend to Vercel:
   ```bash
   vercel --prod
   ```

> **Note:** The WhatsApp bridge (Node.js + Puppeteer) requires a persistent server and cannot run on Vercel. Deploy it alongside the Python backend.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Your Groq API key for AI features |
| `WA_MANAGER_PHONE` | Your WhatsApp number for notifications |
| `LEADFLOW_BACKEND_URL` | Backend URL (for Vercel frontend deployment) |

---

## Troubleshooting

**WhatsApp QR not showing**
- Ensure the Node.js bridge is running: `node whatsapp/server.js`
- Check the bridge is on port 3001: `curl http://localhost:3001/health`

**AI features not working**
- Verify `GROQ_API_KEY` is set in `.env`
- Check backend logs: `uvicorn backend.main:app --reload`

**Leads not auto-capturing from WhatsApp**
- Confirm WhatsApp shows "Connected" (green dot in sidebar)
- Make sure the Python backend is running and the bridge can reach it on port 8000

**Database issues**
- The SQLite database is at `data/leadflow.db`
- To reset: delete the file and restart the backend (it recreates automatically)
