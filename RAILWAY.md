# Railway Deployment Guide

This project requires **two Railway services** to run:

## Service 1: POT Provider

The POT (Proof-of-Origin Token) provider generates tokens to bypass YouTube's bot detection.

### Setup
1. Create a new service in your Railway project
2. Select **"Docker Image"** as the source
3. Enter image: `brainicism/bgutil-ytdlp-pot-provider:latest`
4. No environment variables needed
5. **Important:** Note the internal service URL (e.g., `pot-provider.railway.internal`)

### Settings
- **Port:** 4416 (auto-detected)
- **Restart Policy:** Always

---

## Service 2: Theme Song Bot

The Discord bot that plays theme songs.

### Setup
1. Create a new service in your Railway project
2. Connect to your GitHub repo: `Adamo-O/Theme-Song-Discord-Bot`
3. Railway will auto-detect the Dockerfile

### Environment Variables

| Variable | Value | Description |
|----------|-------|-------------|
| `POT_PROVIDER_URL` | `http://<pot-service>:4416` | Internal URL to POT provider |
| `DISCORD_TOKEN` | `your_token` | Discord bot token |
| `MONGODB_URI` | `mongodb+srv://...` | MongoDB connection string |
| `MONGODB_PASSWORD` | `your_password` | MongoDB password |

**Example `POT_PROVIDER_URL`:**
If your POT provider service is named `pot-provider`, the URL would be:
```
http://pot-provider.railway.internal:4416
```

---

## Deployment Order

1. Deploy **POT Provider** first
2. Wait for it to be healthy (check logs for "Server listening on port 4416")
3. Deploy **Theme Song Bot** with the correct `POT_PROVIDER_URL`

---

## Troubleshooting

### Bot can't connect to POT provider
- Verify both services are in the same Railway project
- Check the internal URL format: `http://<service-name>.railway.internal:4416`
- Check POT provider logs for startup errors

### Still getting YouTube bot detection
- POT provider may need a few seconds to warm up on first request
- Check POT provider logs for token generation errors
- Try restarting the POT provider service

### Audio not playing
- Verify FFmpeg is installed (should be in Dockerfile)
- Check bot has voice permissions in Discord
- Look for errors in bot logs during `play` command
