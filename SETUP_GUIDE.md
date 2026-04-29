# H&G Invoice Sync Server — Railway Deployment Guide
# =====================================================
# Total time: ~15 minutes, one-time only!

## WHAT YOU NEED READY
- Firebase URL: https://hg-invoices-default-rtdb.asia-southeast1.firebasedatabase.app
- Firebase Service Account JSON (already downloaded)
- Anthropic API key (get in Step 1)
- Railway account (free, Step 2)

## STEP 1 — Get Anthropic API Key
1. Go to console.anthropic.com and sign in
2. Click "API Keys" in left menu
3. Click "Create Key" and name it "hg-invoice-sync"
4. Copy the key (starts with sk-ant-)
   Cost: ~RM0.02-0.05 per PDF invoice processed

## STEP 2 — Deploy to Railway.app
1. Go to railway.app and sign up free (use Google account)
2. Click "New Project"
3. Click "Empty Project"
4. Click "Add Service" → "GitHub Repo" or drag & drop the hg-sync-server folder
5. Wait 1-2 minutes to deploy
6. Copy the generated URL e.g. https://hg-sync-server-production.up.railway.app

## STEP 3 — Add Environment Variables in Railway
Click your project → "Variables" tab → Add these:

  ANTHROPIC_API_KEY        = sk-ant-xxxx (your key from Step 1)
  FIREBASE_URL             = https://hg-invoices-default-rtdb.asia-southeast1.firebasedatabase.app
  FIREBASE_SERVICE_ACCOUNT = (open JSON file in Notepad, Ctrl+A, Ctrl+C, paste here — one long line)
  WEBHOOK_SECRET           = hg_cement_sync_2026

After adding variables, Railway auto-redeploys. Wait 1 minute.

## STEP 4 — Test the server
Go to: https://YOUR-RAILWAY-URL/health
Should show: {"status":"healthy","firebase":true}

## STEP 5 — Set up Power Automate (free)
1. Go to make.powerautomate.com
2. Sign in with hgdevelopmententerprise@hotmail.com
3. Click "Create" → "Automated cloud flow"
4. Name: "HG Invoice Sync"
5. Trigger: "When a new email arrives (V3)"
   - Folder: Inbox
   - Include Attachments: Yes
   - Only with Attachments: Yes
6. Add action: "HTTP"
   - Method: POST
   - URI: https://YOUR-RAILWAY-URL/webhook/email
   - Headers:
       Content-Type: application/json
       X-Webhook-Secret: hg_cement_sync_2026
   - Body:
     {"subject":"@{triggerOutputs()?['body/subject']}","from":"@{triggerOutputs()?['body/from']}","attachments":@{triggerOutputs()?['body/attachments']}}
7. Save the flow

## STEP 6 — Set BCC in AutoCount
1. Open any invoice → Send by Email
2. BCC field: hgdevelopmententerprise@hotmail.com
3. This is one-time — AutoCount saves it!

## STEP 7 — Test full flow
1. Send test invoice from AutoCount
2. Wait 30 seconds
3. Check H&G app → new invoice appears automatically!

## COSTS
- Railway: FREE
- Power Automate: FREE  
- Firebase: FREE
- Anthropic: ~RM2-5/month for 100 invoices
