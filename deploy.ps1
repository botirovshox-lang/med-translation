# ============================================================================
# DEPLOYMENT SCRIPT - Medical CAT Translator v5.5
# Automated GitHub Push & Railway Deployment Prep
# ============================================================================

Write-Host "=" * 80
Write-Host "MEDICAL CAT TRANSLATOR v5.5 - AUTOMATED DEPLOYMENT SCRIPT"
Write-Host "=" * 80
Write-Host ""

# Configuration
$PROJECT_DIR = "C:\Users\Shox\med_translation"
$GITHUB_USERNAME = ""  # Will prompt user
$REPO_NAME = "med-translation"
$GITHUB_REPO_URL = ""

# ============================================================================
# STEP 1: Verify Git
# ============================================================================

Write-Host "STEP 1: Verifying Git installation..."
Write-Host "-" * 80

try {
    $gitVersion = git --version
    Write-Host "✅ Git found: $gitVersion"
} catch {
    Write-Host "❌ Git not found. Please install Git from https://git-scm.com"
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 2: Get GitHub Username
# ============================================================================

Write-Host "STEP 2: GitHub Configuration"
Write-Host "-" * 80

$GITHUB_USERNAME = Read-Host "Enter your GitHub username"

if ([string]::IsNullOrWhiteSpace($GITHUB_USERNAME)) {
    Write-Host "❌ GitHub username is required"
    exit 1
}

$GITHUB_REPO_URL = "https://github.com/$GITHUB_USERNAME/$REPO_NAME.git"

Write-Host "✅ GitHub repository will be: $GITHUB_REPO_URL"
Write-Host ""

# ============================================================================
# STEP 3: Verify Local Repository
# ============================================================================

Write-Host "STEP 3: Verifying local repository..."
Write-Host "-" * 80

cd $PROJECT_DIR

# Check if git repo exists
if (-not (Test-Path ".git")) {
    Write-Host "❌ Git repository not found in $PROJECT_DIR"
    Write-Host "   Repository should have been initialized in Phase 1"
    exit 1
}

Write-Host "✅ Git repository found"

# Check branch
$currentBranch = git branch --show-current
Write-Host "✅ Current branch: $currentBranch"

# Check commits
$commitCount = git log --oneline | Measure-Object -Line
Write-Host "✅ Total commits: $($commitCount.Lines)"

# Check status
$gitStatus = git status --short
if ([string]::IsNullOrWhiteSpace($gitStatus -replace "M.*\.pyc|M.*\.db|\?.*test_output")) {
    Write-Host "✅ Working directory clean (ignoring .pycache, .db, test files)"
} else {
    Write-Host "⚠️  Note: .pycache and .db files will be ignored by .gitignore"
}

Write-Host ""

# ============================================================================
# STEP 4: Rename Branch to main
# ============================================================================

Write-Host "STEP 4: Updating branch name to 'main' (GitHub standard)..."
Write-Host "-" * 80

if ($currentBranch -eq "master") {
    Write-Host "Renaming branch: master → main"
    git branch -M main
    Write-Host "✅ Branch renamed to main"
} elseif ($currentBranch -eq "main") {
    Write-Host "✅ Already on 'main' branch"
} else {
    Write-Host "⚠️  On branch: $currentBranch (expected: main or master)"
}

Write-Host ""

# ============================================================================
# STEP 5: Configure Git Remote
# ============================================================================

Write-Host "STEP 5: Configuring GitHub remote..."
Write-Host "-" * 80

# Check if remote already exists
$remoteExists = git remote get-url origin 2>$null

if ($remoteExists) {
    Write-Host "⚠️  Remote 'origin' already exists: $remoteExists"
    $updateRemote = Read-Host "Update to new URL? (y/n)"

    if ($updateRemote -eq "y") {
        git remote remove origin
        git remote add origin $GITHUB_REPO_URL
        Write-Host "✅ Remote updated to: $GITHUB_REPO_URL"
    } else {
        Write-Host "✅ Using existing remote"
    }
} else {
    Write-Host "Adding new remote: origin"
    git remote add origin $GITHUB_REPO_URL
    Write-Host "✅ Remote added: $GITHUB_REPO_URL"
}

# Verify remote
$verifyRemote = git remote get-url origin
Write-Host "✅ Remote verified: $verifyRemote"

Write-Host ""

# ============================================================================
# STEP 6: Display Push Preview
# ============================================================================

Write-Host "STEP 6: Push Preview"
Write-Host "-" * 80

Write-Host "Repository: $GITHUB_REPO_URL"
Write-Host "Branch: main"

$logPreview = git log --oneline -5
Write-Host "Last 5 commits:"
Write-Host $logPreview

Write-Host ""
$confirm = Read-Host "Ready to push to GitHub? (y/n)"

if ($confirm -ne "y") {
    Write-Host "❌ Push cancelled by user"
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 7: Push to GitHub
# ============================================================================

Write-Host "STEP 7: Pushing code to GitHub..."
Write-Host "-" * 80

Write-Host "Executing: git push -u origin main"
Write-Host ""

try {
    git push -u origin main

    $pushStatus = $LASTEXITCODE

    if ($pushStatus -eq 0) {
        Write-Host ""
        Write-Host "✅ PUSH SUCCESSFUL!"
        Write-Host ""
        Write-Host "Your repository is now on GitHub at:"
        Write-Host "   $GITHUB_REPO_URL"
    } else {
        Write-Host ""
        Write-Host "❌ Push failed with exit code: $pushStatus"
        Write-Host ""
        Write-Host "Common issues:"
        Write-Host "1. GitHub credentials not configured"
        Write-Host "   → Run: git config --global user.name 'Your Name'"
        Write-Host "   → Run: git config --global user.email 'your@email.com'"
        Write-Host ""
        Write-Host "2. Repository doesn't exist on GitHub"
        Write-Host "   → Create at: https://github.com/new"
        Write-Host "   → Repository name: $REPO_NAME"
        Write-Host "   → Make it PRIVATE"
        Write-Host ""
        Write-Host "3. Authentication token expired"
        Write-Host "   → Create Personal Access Token at:"
        Write-Host "   → https://github.com/settings/tokens"
        Write-Host "   → Paste token when prompted for password"
        exit 1
    }
} catch {
    Write-Host "❌ Error during push:"
    Write-Host $_.Exception.Message
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 8: Verify Push
# ============================================================================

Write-Host "STEP 8: Verifying push..."
Write-Host "-" * 80

$localBranch = git rev-parse HEAD
Write-Host "✅ Local HEAD: $localBranch"

Write-Host ""
Write-Host "🎉 GITHUB PUSH COMPLETE!"
Write-Host ""

# ============================================================================
# STEP 9: Next Steps
# ============================================================================

Write-Host "NEXT STEPS FOR RAILWAY DEPLOYMENT:"
Write-Host "=" * 80
Write-Host ""
Write-Host "1. Open Railway Dashboard:"
Write-Host "   → https://railway.app"
Write-Host ""
Write-Host "2. Create New Project:"
Write-Host "   → Click 'New Project'"
Write-Host "   → Select 'Deploy from GitHub'"
Write-Host "   → Authorize Railway to access GitHub"
Write-Host "   → Select repository: $REPO_NAME"
Write-Host ""
Write-Host "3. Wait for Build (2-3 minutes):"
Write-Host "   → Railway auto-detects Dockerfile"
Write-Host "   → Docker image builds automatically"
Write-Host ""
Write-Host "4. Set Environment Variables:"
Write-Host "   → Go to Variables tab"
Write-Host "   → Add:"
Write-Host "      ENVIRONMENT=production"
Write-Host "      LOG_LEVEL=INFO"
Write-Host "      OPENAI_API_KEY=sk-... (your key)"
Write-Host "      GOOGLE_TRANSLATE_API_KEY=... (if needed)"
Write-Host "      ANTHROPIC_API_KEY=sk-ant-... (if needed)"
Write-Host ""
Write-Host "5. Deploy:"
Write-Host "   → Railway auto-deploys after variables are set"
Write-Host "   → Status should show 'Live' (green checkmark)"
Write-Host ""
Write-Host "6. Access App:"
Write-Host "   → Look for Domain in deployment details"
Write-Host "   → URL format: https://med-translation-prod.up.railway.app"
Write-Host ""
Write-Host "📊 Estimated Railway deployment time: 5-10 minutes"
Write-Host ""
Write-Host "=" * 80
Write-Host "✅ GITHUB PUSH COMPLETE - READY FOR RAILWAY!"
Write-Host "=" * 80
