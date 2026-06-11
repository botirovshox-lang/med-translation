# DEPLOYMENT INSTRUCTIONS - Medical CAT Translator v5.5

**Status:** ✅ **READY FOR PRODUCTION**  
**Date:** 2026-06-11  
**Target:** Railway.app

---

## 📋 Pre-Deployment Checklist

- [x] All modules tested ✅
- [x] Production E2E verification passed ✅
- [x] Docker image configured ✅
- [x] Railway.json created ✅
- [x] Environment variables template ready ✅
- [x] Documentation complete ✅
- [ ] GitHub repository created ← **NEXT**
- [ ] Repository pushed to GitHub ← **NEXT**
- [ ] Railway project connected ← **NEXT**
- [ ] Environment variables set in Railway ← **NEXT**

---

## STEP 1: Create GitHub Repository

### Option A: Via GitHub Web (Easiest)

1. Open browser → https://github.com/new
2. Fill in:
   - **Repository name:** `med-translation`
   - **Description:** Medical CAT Translator v5.5 - Advanced medical document translation system
   - **Privacy:** Select **Private** (contains business logic)
   - **Initialize:** Leave unchecked (we already have git)
3. Click **Create repository**
4. GitHub shows you the push commands → **Copy them**

### Option B: Via GitHub CLI

```bash
# If you have GitHub CLI installed
gh repo create med-translation --private --source=. --remote=origin --push
```

---

## STEP 2: Add GitHub Remote & Push

Once your GitHub repo is created, run these commands:

### EXACT COMMANDS TO RUN

```bash
# Open PowerShell and navigate to project
cd C:\Users\Shox\med_translation

# 1. Add GitHub remote (REPLACE YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/med-translation.git

# 2. Rename branch from master to main (GitHub standard)
git branch -M main

# 3. Verify the remote is set correctly
git remote -v

# Expected output:
# origin  https://github.com/YOUR_USERNAME/med-translation.git (fetch)
# origin  https://github.com/YOUR_USERNAME/med-translation.git (push)

# 4. Push all commits to GitHub
git push -u origin main

# Expected output:
# Enumerating objects: XX, done.
# Counting objects: 100% (XX/XX), done.
# ...
# * [new branch]      main -> main
# Branch 'main' set up to track remote branch 'main' from 'origin'.
```

### ⚠️ IMPORTANT NOTES

- **Replace `YOUR_USERNAME`** with your actual GitHub username
- First push may take 30-60 seconds
- If you get authentication errors, use GitHub Personal Access Token
- Make sure your GitHub credentials are configured locally

---

## STEP 3: Verify Push to GitHub

Once push completes:

```bash
# Verify all commits are on GitHub
git log --oneline -8

# Check remote status
git status

# Expected: "Your branch is up to date with 'origin/main'"
```

Or check in browser: https://github.com/YOUR_USERNAME/med-translation

---

## STEP 4: Deploy to Railway

### 4.1 Create Railway Account (If needed)

1. Open https://railway.app
2. Sign up with GitHub (recommended - auto-connects)
3. Authorize Railway to access GitHub

### 4.2 Create Railway Project

1. Click **New Project**
2. Select **Deploy from GitHub**
3. Select your repository: `med-translation`
4. Railway will:
   - Detect Dockerfile ✅
   - Start building Docker image (2-3 minutes)
   - Deploy container

### 4.3 Set Environment Variables

Once Railway project is created:

1. Go to **Variables** tab
2. Add each variable (click + Add Variable):

```
ENVIRONMENT                  production
LOG_LEVEL                    INFO
OPENAI_API_KEY               sk-... (your key)
GOOGLE_TRANSLATE_API_KEY     (your key if using)
ANTHROPIC_API_KEY            sk-ant-... (your key)
STREAMLIT_SERVER_PORT        8501
```

**How to add variables:**
- Click **+ Add Variable**
- Enter name
- Enter value
- Click checkmark
- Repeat for each variable

### 4.4 Monitor Deployment

1. Go to **Deployments** tab
2. Watch status:
   - Building (Docker image) → 2-3 min
   - Deploying (Container startup) → 1 min
   - Live (Running) ✅

3. View logs:
   - Click deployment
   - See Streamlit startup logs
   - Look for: `You can now view your Streamlit app in your browser`

### 4.5 Access Your App

Once status shows **Live** ✅:

1. Look for **Domain** in the deployment details
2. It will be something like: `https://med-translation-prod.up.railway.app`
3. Click the link or copy to browser
4. Streamlit interface should load!

---

## STEP 5: Test in Production

Once app is live:

1. **Check Streamlit loads:**
   - Page loads without errors
   - All controls visible
   - No red error boxes

2. **Test basic functionality:**
   - Click any button
   - Verify no errors in logs
   - Check Railway logs for any issues

3. **Full pipeline test (optional but recommended):**
   - Import a test DOCX file (small, 5-10 segments)
   - Click "Run Preflight Analysis"
   - Verify preflight data loads
   - Check database still works

4. **Monitor performance:**
   - Railway Dashboard → Metrics
   - Check CPU, memory, response time
   - Should be well within limits

---

## TROUBLESHOOTING

### Build Fails

**Error: "Cannot find module X"**

- Check `med_translation/requirements.txt`
- Verify all imports exist
- Rebuild in Railway dashboard

**Error: "Port already in use"**

- Railway automatically assigns ports
- Ensure `Procfile` uses `$PORT` variable ✅ (already done)

### App Crashes on Startup

**Check logs:**
```
Railway Dashboard → Deployments → [your deployment] → Logs
```

**Common issues:**
- Missing environment variables → Add in Variables tab
- Database not found → Uses SQLite, should work
- Module import error → Check requirements.txt

**Solution:**
- Fix the issue locally
- Push to GitHub: `git push origin main`
- Railway redeploys automatically (if auto-deploy enabled)

### Environment Variables Not Working

1. Verify variables are set in Railway Variables tab
2. Check spelling (case-sensitive)
3. Restart deployment:
   - Deployments tab
   - Click current deployment
   - Click "Redeploy"

### Slow Performance

1. Check Railway metrics (CPU, memory)
2. If overloaded, upgrade plan in Railway dashboard
3. Check app logs for slow operations
4. Review preflight_analyzer performance (should be <120s)

---

## ROLLBACK (If Something Goes Wrong)

### Via Railway Dashboard

1. Go to **Deployments** tab
2. Find the previous successful deployment
3. Click **Redeploy**
4. Wait for re-deployment
5. App reverts to previous version ✅

**Time to rollback:** 2-3 minutes

### Via Git

```bash
cd C:\Users\Shox\med_translation

# Find the commit to revert to
git log --oneline -10

# Revert to specific commit (find hash from above)
git reset --hard <commit-hash>

# Push (this will trigger Railway redeploy if auto-deploy enabled)
git push origin main --force

# ⚠️ Only use --force if you're sure about what you're doing
```

---

## STEP 6: Enable Auto-Deploy (Recommended)

So that every `git push` automatically redeploys:

1. Railway Dashboard → [Your project]
2. Click **Settings**
3. Find **Deploy on Git push**
4. Toggle: **ON** ✅

Now whenever you push to GitHub:
```bash
git push origin main
```

Railway automatically:
- Detects the push
- Rebuilds Docker image
- Redeploys container
- Updates live app

**Time to auto-deploy:** 3-5 minutes per push

---

## STEP 7: Monitor in Production

### Daily/Weekly Checks

```bash
# View live logs
railway logs

# Or via dashboard: Railway → Deployments → Logs
```

### Check Metrics

1. Railway Dashboard → Metrics tab
2. Monitor:
   - CPU usage (should be < 50%)
   - Memory usage (should be < 200 MB)
   - Response time (should be < 1 second)

### Set Up Alerts (Optional)

Railway can notify you of failures:
1. Dashboard → Alerts
2. Enable deployment failure notifications
3. Add email

---

## STEP 8: Update & Maintain

### To Update Code

```bash
# Make changes locally
# ... edit files ...

# Test locally
python test_production_e2e.py

# Commit
git add .
git commit -m "Your change description"

# Push (auto-deploys if enabled)
git push origin main

# Monitor deployment in Railway dashboard
# Wait for green checkmark
```

### Dependencies Update

```bash
# Edit med_translation/requirements.txt
# Add or update version numbers

# Commit
git add med_translation/requirements.txt
git commit -m "Update dependencies"

# Push
git push origin main

# Railway rebuilds with new dependencies automatically
```

### Database Migrations

If you need to change database schema:
1. Test locally first
2. Create migration script
3. Run before deployment
4. Commit and push

---

## STEP 9: Production Support

### Real-Time Monitoring

```bash
# Stream logs in real-time
railway logs --follow

# Or one-time check
railway logs
```

### Performance Analysis

1. Railway Dashboard → Metrics
2. Export data for analysis
3. Identify slow operations
4. Optimize code
5. Push update

### Scaling (If Needed)

If app gets slow:
1. Railway Dashboard → Plan
2. Upgrade to higher tier
3. Scales up automatically
4. Monitor performance improvement

---

## STEP 10: Backup & Recovery

### Database Backup

SQLite database is at: `/med_translation/data/cat_translator.db`

On Railway:
1. Download via Railway dashboard (or SFTP if available)
2. Keep local backups
3. Test restore procedures monthly

### Full Project Backup

```bash
# GitHub already has your code
# Plus local copy on your machine

# Verify:
git remote -v
git log --oneline -5
```

---

## SUMMARY - Command Cheat Sheet

```bash
# 1. Add GitHub remote
git remote add origin https://github.com/YOUR_USERNAME/med-translation.git

# 2. Switch to main branch
git branch -M main

# 3. Push to GitHub
git push -u origin main

# 4. Future pushes
git push origin main

# 5. Check status
git status

# 6. View logs locally
git log --oneline -10

# 7. View live logs on Railway (if CLI installed)
railway logs

# 8. Rollback (if needed)
git reset --hard <commit-hash>
git push origin main --force
```

---

## QUICK REFERENCE

| Task | Command | Time |
|------|---------|------|
| Create GitHub repo | Web: https://github.com/new | 2 min |
| Push to GitHub | `git push -u origin main` | 1 min |
| First Railway deploy | New Project → Deploy | 5 min |
| Set env vars | Railway Dashboard | 2 min |
| Total time to production | | **10 min** |

---

## SUPPORT

**Need help?**

1. Check **RAILWAY_DEPLOYMENT.md** for detailed guide
2. Check **PRODUCTION_STATUS.md** for system status
3. Check Railway docs: https://docs.railway.app
4. Check GitHub docs: https://docs.github.com

**Still stuck?**
- Review logs in Railway dashboard
- Test locally: `streamlit run app_v55.py`
- Check git status: `git status`

---

**READY TO DEPLOY!** 🚀

Next step: Follow STEP 1 to create GitHub repository.

---

Generated: 2026-06-11  
System: Medical CAT Translator v5.5  
Status: Production Ready
