# Railway Deployment Guide - Medical CAT Translator v5.5

## Prerequisites

Before deploying to Railway, you need:
- [ ] GitHub account (to host the repository)
- [ ] Railway account (https://railway.app)
- [ ] GitHub Personal Access Token (for Railway to access your repo)

---

## Step 1: Create GitHub Repository (One-time)

### 1.1 Create a new repo on GitHub
1. Go to https://github.com/new
2. Repository name: `med-translation`
3. Description: `Medical CAT Translator v5.5`
4. Choose **Private** (since it contains business logic)
5. Click **Create repository**

### 1.2 Add GitHub remote to local repo
```bash
cd C:\Users\Shox\med_translation
git remote add origin https://github.com/YOUR_USERNAME/med-translation.git
git branch -M main
git push -u origin main
```

---

## Step 2: Deploy to Railway

### 2.1 Connect Railway to GitHub
1. Go to https://railway.app and sign in (or create account)
2. Click **New Project**
3. Select **Deploy from GitHub**
4. Authorize Railway to access GitHub
5. Select repository: `med-translation`
6. Railway will automatically detect Dockerfile and start building

### 2.2 Configure Environment Variables in Railway

Once the project is created, go to **Variables** tab and add:

```
ENVIRONMENT=production
LOG_LEVEL=INFO
OPENAI_API_KEY=sk-...your-key...
GOOGLE_TRANSLATE_API_KEY=your-google-key-here
ANTHROPIC_API_KEY=sk-ant-...your-key...
STREAMLIT_SERVER_PORT=8501
```

**⚠️ Security Note:** Use Railway's built-in secret manager — DO NOT paste secrets in .env file that gets committed to Git.

### 2.3 Configure Service Settings

In Railway dashboard for your service:
1. **Settings** tab
2. **Port:** 8501 (for Streamlit)
3. **Build:** Should auto-detect Dockerfile
4. **Deploy on Git push:** Enable (auto-deploy on each push)

---

## Step 3: Verify Deployment

Once Railway shows status "Deployed":

### 3.1 Open the app
- Click "View Logs" to see Streamlit startup
- Look for: `You can now view your Streamlit app in your browser.`
- App URL will be shown: `https://{app-name}.up.railway.app`

### 3.2 Test the app
1. Open the Railway app URL in browser
2. Verify Streamlit interface loads
3. Try importing a test DOCX file
4. Run through a single segment translation

### 3.3 Monitor logs
```bash
# Via Railway CLI (if installed)
railway logs

# Or use Railway Dashboard → Deployments → Logs
```

---

## Troubleshooting

### Issue: Build fails with "No module named 'streamlit'"

**Solution:** Ensure `med_translation/requirements.txt` is correctly installed.

Check Dockerfile COPY command:
```dockerfile
COPY med_translation/requirements.txt ./requirements.txt
```

### Issue: App crashes with "Port already in use"

**Solution:** Railway automatically assigns ports. Ensure Procfile uses `$PORT`:
```procfile
web: streamlit run app_v55.py --server.port=$PORT --server.address=0.0.0.0
```

### Issue: Database file not found

**Solution:** SQLite database is created on first run. Ensure `med_translation/data/` directory is writable.

For persistent storage across deploys, use Railway's PostgreSQL add-on instead of SQLite.

### Issue: Authentication fails (OpenAI, Google, etc.)

**Solution:** Check environment variables in Railway dashboard:
1. **Variables** tab
2. Verify each key is set correctly
3. Use Railway CLI to test:
   ```bash
   railway env
   ```

---

## Updating the App

Whenever you make changes:

1. **Commit locally:**
   ```bash
   cd C:\Users\Shox\med_translation
   git add .
   git commit -m "Update: Your change description"
   ```

2. **Push to GitHub:**
   ```bash
   git push origin main
   ```

3. **Railway auto-deploys** (if "Deploy on Git push" is enabled)
   - Check Railway dashboard for build progress
   - Green checkmark = deployment successful

---

## Production Checklist

- [ ] GitHub repository created and configured
- [ ] Railway project created and connected to GitHub
- [ ] All environment variables set in Railway dashboard
- [ ] Dockerfile builds successfully
- [ ] App starts and Streamlit interface loads
- [ ] Test DOCX import works
- [ ] Test translation works end-to-end
- [ ] Database persists data between restarts
- [ ] Logs are being collected in Railway dashboard
- [ ] Auto-deploy on Git push is enabled

---

## Monitoring & Maintenance

### Check app health
- Railway dashboard → Deployments tab
- Look for green status indicator
- Recent logs show no errors

### Monitor resource usage
- Railway dashboard → Metrics tab
- CPU, Memory, Network statistics

### Update dependencies
- Edit `med_translation/requirements.txt`
- Push to GitHub
- Railway auto-redeploys with new packages

---

## Rollback

If deployment breaks:

1. Go to Railway dashboard → Deployments
2. Find the previous successful deployment
3. Click **Redeploy**
4. Railway will rebuild and restore from that commit

Or locally:
```bash
git log --oneline  # Find previous commit
git reset --hard <commit-hash>
git push origin main --force  # Be careful with force push!
```

---

## Next Steps

After successful Railway deployment:
- [ ] Phase 3: Production E2E verification
- [ ] Set up continuous monitoring
- [ ] Configure logging and alerts
- [ ] Document production URLs and credentials (in secure location)

---

**For questions:** Check Railway docs at https://docs.railway.app
