# Microsoft Teams Channel Setup

## Step 1: Create the Teams Channel

1. Open Microsoft Teams
2. Go to your DevOps team
3. Click the three dots (...) next to your team name
4. Select **Add channel**
5. Enter channel name: **`Sentry Critical Alerts`** (or your preferred name)
6. Description: "Automated Sentry issue triage and critical alert notifications from AI analysis"
7. Privacy: **Standard** (visible to everyone in the team)
8. Click **Add**

## Step 2: Create Incoming Webhook

1. In the new channel, click the three dots (...) at the top
2. Select **Connectors** (or **Workflows** in newer Teams versions)
3. Search for **Incoming Webhook**
4. Click **Configure** (or **Add** for Incoming Webhook)
5. Name: **Sentry Alert Agent**
6. Optionally upload an icon/image
7. Click **Create**
8. **Copy the webhook URL** - this is your `TEAMS_WEBHOOK_URL`
9. Click **Done**

## Step 3: Configure Environment Variables

Create or update your environment file (e.g., `/path/to/private/sentry-triage.env`):

```bash
# Sentry Configuration
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=replace-with-token
SENTRY_ORG=replace-with-org-slug
SENTRY_PROJECTS=backend,ai-service
SENTRY_QUERY=is:unresolved
SENTRY_OUTPUT_DIR=/var/tmp/sentry-playbooks
SENTRY_CRITICAL_PRIORITIES=P0,P1

# Teams Webhook Configuration
TEAMS_WEBHOOK_URL=https://example.com/webhook
TEAMS_TIMEOUT=15
TEAMS_MAX_LAST_SEEN_AGE_HOURS=24

# Optional: Ignore file for noise reduction
SENTRY_IGNORE_FILE=/path/to/private/sentry-ignore.json
```

## Step 4: Test the Webhook

Run a dry-run test to see what would be sent:

```bash
cd ~/sre-alert-agent
python3 agents/sender.py --dry-run
```

If you have approved alerts, send them:

```bash
python3 agents/sender.py
```

## Webhook Security Notes

- The webhook URL is sensitive - treat it like a password
- Anyone with the URL can post to your channel
- Store it in a private env file outside the repo
- Never commit the webhook URL to version control
- Consider rotating the webhook periodically
- If compromised, delete the old connector and create a new one

## Troubleshooting

### Webhook not working?
- Verify the URL is complete and hasn't been truncated
- Check if the connector is still active in Teams (go to channel → Connectors)
- Test with a simple curl command:
  ```bash
  curl -H "Content-Type: application/json" \
       -d '{"text":"Test message"}' \
       "$TEAMS_WEBHOOK_URL"
  ```

### Alerts not appearing?
- Check that `send_status: send` is in the front matter of approved alert files
- Verify files are in the `alerts/approved/` directory
- Check the `TEAMS_MAX_LAST_SEEN_AGE_HOURS` setting isn't filtering out stale alerts
