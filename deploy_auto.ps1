# ============================================================================
# AUTOMATED DEPLOYMENT SCRIPT - Medical CAT Translator v5.5
# NO USER INPUT REQUIRED - Fully automated
# ============================================================================

param(
    [string]$GitHubUsername = "shoxruz",  # Change this to your GitHub username
    [string]$RepoName = "med-translation",
    [string]$BranchName = "main"
)

Write-Host "=" * 80
Write-Host "AUTOMATED DEPLOYMENT - Medical CAT Translator v5.5"
Write-Host "=" * 80
Write-Host ""

$PROJECT_DIR = "C:\Users\Shox\med_translation"
$GITHUB_REPO_URL = "https://github.com/$GitHubUsername/$RepoName.git"

Write-Host "Configuration:"
Write-Host "  GitHub Username: $GitHubUsername"
Write-Host "  Repository: $RepoName"
Write-Host "  Branch: $BranchName"
Write-Host "  URL: $GITHUB_REPO_URL"
Write-Host ""

# ============================================================================
# STEP 1: Verify Git
# ============================================================================

Write-Host "STEP 1: Verifying Git..."
Write-Host "-" * 80

try {
    $gitVersion = git --version
    Write-Host "✅ Git: $gitVersion"
} catch {
    Write-Host "❌ Git not installed!"
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 2: Navigate to Project
# ============================================================================

Write-Host "STEP 2: Setting up project directory..."
Write-Host "-" * 80

if (-not (Test-Path $PROJECT_DIR)) {
    Write-Host "❌ Project directory not found: $PROJECT_DIR"
    exit 1
}

cd $PROJECT_DIR
Write-Host "✅ Working directory: $(Get-Location)"

if (-not (Test-Path ".git")) {
    Write-Host "❌ Git repository not found"
    exit 1
}

Write-Host "✅ Git repository found"
Write-Host ""

# ============================================================================
# STEP 3: Prepare Repository
# ============================================================================

Write-Host "STEP 3: Preparing repository..."
Write-Host "-" * 80

# Get current branch
$currentBranch = git branch --show-current
Write-Host "Current branch: $currentBranch"

# Rename to main if on master
if ($currentBranch -eq "master") {
    Write-Host "Renaming branch: master → main"
    git branch -M main
    Write-Host "✅ Branch renamed to main"
} else {
    Write-Host "✅ Already on main or equivalent"
}

# Check commits
$logCount = (git log --oneline | Measure-Object -Line).Lines
Write-Host "✅ Total commits: $logCount"

Write-Host ""

# ============================================================================
# STEP 4: Configure Remote
# ============================================================================

Write-Host "STEP 4: Configuring GitHub remote..."
Write-Host "-" * 80

# Check if remote exists
$remoteExists = git remote get-url origin 2>$null

if ($remoteExists) {
    Write-Host "Remote already exists: $remoteExists"
    Write-Host "Updating to: $GITHUB_REPO_URL"
    git remote remove origin
    git remote add origin $GITHUB_REPO_URL
    Write-Host "✅ Remote updated"
} else {
    Write-Host "Adding new remote: origin"
    git remote add origin $GITHUB_REPO_URL
    Write-Host "✅ Remote added"
}

# Verify
$verifyRemote = git remote get-url origin
Write-Host "✅ Verified: $verifyRemote"

Write-Host ""

# ============================================================================
# STEP 5: Push to GitHub
# ============================================================================

Write-Host "STEP 5: Pushing to GitHub..."
Write-Host "-" * 80
Write-Host "Executing: git push -u origin main"
Write-Host ""

try {
    # Attempt push
    git push -u origin main 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "✅ PUSH SUCCESSFUL!"
        Write-Host ""
        Write-Host "Repository is now on GitHub:"
        Write-Host "   $GITHUB_REPO_URL"
    } else {
        Write-Host ""
        Write-Host "❌ Push failed with exit code: $LASTEXITCODE"
        Write-Host ""
        Write-Host "Common causes:"
        Write-Host "1. GitHub credentials not configured"
        Write-Host "   Run: git config --global user.name 'Your Name'"
        Write-Host "   Run: git config --global user.email 'your@email.com'"
        Write-Host ""
        Write-Host "2. Repository not created on GitHub yet"
        Write-Host "   Create at: https://github.com/new"
        Write-Host ""
        Write-Host "3. Authentication token expired"
        Write-Host "   Create new token at: https://github.com/settings/tokens"
        Write-Host ""
        exit 1
    }
} catch {
    Write-Host "❌ Error: $($_.Exception.Message)"
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 6: Verify
# ============================================================================

Write-Host "STEP 6: Verifying push..."
Write-Host "-" * 80

$localHead = git rev-parse HEAD
Write-Host "✅ Local HEAD: $localHead"

Write-Host ""

# ============================================================================
# STEP 7: Display Next Steps
# ============================================================================

Write-Host "✅ GITHUB PUSH COMPLETE!"
Write-Host ""
Write-Host "NEXT STEPS - RAILWAY DEPLOYMENT:"
Write-Host "=" * 80
Write-Host ""
Write-Host "1. OPEN RAILWAY DASHBOARD"
Write-Host "   → https://railway.app"
Write-Host ""
Write-Host "2. CREATE NEW PROJECT"
Write-Host "   → Click 'New Project'"
Write-Host "   → Select 'Deploy from GitHub'"
Write-Host "   → Authorize Railway (if first time)"
Write-Host "   → Select repository: $RepoName"
Write-Host ""
Write-Host "3. WAIT FOR BUILD (2-3 minutes)"
Write-Host "   → Railway auto-detects Dockerfile"
Write-Host "   → Docker image builds automatically"
Write-Host "   → Deployment status shown in dashboard"
Write-Host ""
Write-Host "4. SET ENVIRONMENT VARIABLES"
Write-Host "   → Go to 'Variables' tab"
Write-Host "   → Click '+ Add Variable' for each:"
Write-Host "      ENVIRONMENT = production"
Write-Host "      LOG_LEVEL = INFO"
Write-Host "      OPENAI_API_KEY = sk-... (your key)"
Write-Host "      GOOGLE_TRANSLATE_API_KEY = ... (if needed)"
Write-Host "      ANTHROPIC_API_KEY = sk-ant-... (if needed)"
Write-Host ""
Write-Host "5. DEPLOYMENT AUTOMATIC"
Write-Host "   → Railway auto-deploys after variables set"
Write-Host "   → Status changes to 'Live' (green checkmark)"
Write-Host ""
Write-Host "6. ACCESS YOUR APP"
Write-Host "   → Click deployment domain link"
Write-Host "   → Or go to: https://med-translation-prod.up.railway.app"
Write-Host "   → Streamlit interface should load ✅"
Write-Host ""
Write-Host "⏱️  Estimated Railway time: 5-10 minutes"
Write-Host ""
Write-Host "=" * 80
Write-Host "✅ DEPLOYMENT PREP COMPLETE - Ready for Railway!"
Write-Host "=" * 80
