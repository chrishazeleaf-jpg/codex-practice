#!/usr/bin/env bash
# push-to-github.sh
# Usage: bash push-to-github.sh <github-repo-url>
#
# Pushes the current local git repository to a new GitHub repo.
# Run this from inside your local project directory.
#
# Example:
#   bash push-to-github.sh https://github.com/yourname/your-repo.git

set -e

REPO_URL="$1"

if [ -z "$REPO_URL" ]; then
  echo "Usage: bash push-to-github.sh <github-repo-url>"
  echo ""
  echo "Example:"
  echo "  bash push-to-github.sh https://github.com/yourname/your-repo.git"
  echo ""
  echo "Steps to get the URL:"
  echo "  1. Go to https://github.com/new"
  echo "  2. Create an empty repo (no README, no .gitignore)"
  echo "  3. Copy the HTTPS URL shown on the next page"
  exit 1
fi

# 1. Initialise git if not already a repo
if [ ! -d ".git" ]; then
  echo ">>> Initialising git repository..."
  git init
fi

# 2. Stage and commit everything if there are no commits yet
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo ">>> No commits found. Staging all files and creating initial commit..."
  git add -A
  git commit -m "Initial commit"
fi

# 3. Set or update the 'origin' remote
if git remote get-url origin >/dev/null 2>&1; then
  echo ">>> Updating existing 'origin' remote to $REPO_URL"
  git remote set-url origin "$REPO_URL"
else
  echo ">>> Adding 'origin' remote: $REPO_URL"
  git remote add origin "$REPO_URL"
fi

# 4. Push — try 'main' first, fall back to 'master'
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "main")
echo ">>> Pushing branch '$BRANCH' to GitHub..."
git push -u origin "$BRANCH"

echo ""
echo "Done! Your project is now on GitHub: $REPO_URL"
