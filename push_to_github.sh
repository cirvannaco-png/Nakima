#!/data/data/com.termux/files/usr/bin/bash
# push_to_github.sh — turns this local Nakima folder into a live GitHub repo.
#
# Usage (from inside the nakima/ folder, in Termux):
#   bash push_to_github.sh
#
# It will prompt for anything not already set as an env var:
#   GITHUB_USERNAME   your GitHub username or org name
#   GITHUB_TOKEN      a Personal Access Token with 'repo' scope
#                      (https://github.com/settings/tokens -> Generate new
#                      token (classic) -> check "repo")
#   REPO_NAME         name for the new repo (default: nakima)
#   REPO_PRIVATE      true/false (default: true)
#
# Nothing here ever sends your token anywhere except api.github.com and
# github.com — it's not shared with any AI, and it's never written to disk.

set -euo pipefail

command -v git   >/dev/null 2>&1 || { echo "git not found. Run: pkg install git"; exit 1; }
command -v curl  >/dev/null 2>&1 || { echo "curl not found. Run: pkg install curl"; exit 1; }

if [ ! -f "core/config.py" ] || [ ! -f "requirements.txt" ]; then
  echo "Run this from inside the nakima/ project folder (core/config.py not found here)."
  exit 1
fi

read_var() {
  local var_name="$1" prompt="$2" is_secret="${3:-false}"
  if [ -z "${!var_name:-}" ]; then
    if [ "$is_secret" = "true" ]; then
      read -r -s -p "$prompt: " value; echo
    else
      read -r -p "$prompt: " value
    fi
    export "$var_name=$value"
  fi
}

read_var GITHUB_USERNAME "GitHub username or org"
read_var GITHUB_TOKEN "GitHub Personal Access Token (repo scope)" true
read_var REPO_NAME "Repo name [nakima]"
REPO_NAME="${REPO_NAME:-nakima}"
read_var REPO_PRIVATE "Private repo? true/false [true]"
REPO_PRIVATE="${REPO_PRIVATE:-true}"

API="https://api.github.com"

echo "Checking whether ${GITHUB_USERNAME}/${REPO_NAME} already exists..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  "${API}/repos/${GITHUB_USERNAME}/${REPO_NAME}")

if [ "$STATUS" = "404" ]; then
  echo "Creating ${GITHUB_USERNAME}/${REPO_NAME}..."
  # Try as a user repo first; if GITHUB_USERNAME is actually an org this
  # 404s/422s and we fall back to the org endpoint.
  CREATE_STATUS=$(curl -s -o /tmp/gh_create_resp.json -w "%{http_code}" \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "${API}/user/repos" \
    -d "{\"name\":\"${REPO_NAME}\",\"private\":${REPO_PRIVATE}}")

  if [ "$CREATE_STATUS" != "201" ]; then
    echo "User-repo creation returned $CREATE_STATUS, trying org endpoint..."
    curl -s -o /tmp/gh_create_resp.json -w "%{http_code}" \
      -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      "${API}/orgs/${GITHUB_USERNAME}/repos" \
      -d "{\"name\":\"${REPO_NAME}\",\"private\":${REPO_PRIVATE}}" > /dev/null
  fi
elif [ "$STATUS" = "200" ]; then
  echo "Repo already exists — will push into it."
else
  echo "Unexpected response checking repo (HTTP $STATUS). Check your token/username."
  exit 1
fi

if [ ! -d ".git" ]; then
  git init -q
fi

git add -A
if ! git diff --cached --quiet; then
  git commit -q -m "Nakima: reconciled scaffold, auth fix, real file-block + validation parsing"
else
  echo "Nothing new to commit."
fi
git branch -M main

REMOTE_URL="https://${GITHUB_USERNAME}:${GITHUB_TOKEN}@github.com/${GITHUB_USERNAME}/${REPO_NAME}.git"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

echo "Pushing to GitHub..."
git push -u origin main

# Strip the token back out of the stored remote URL so it doesn't sit in
# .git/config in plaintext after this script exits.
git remote set-url origin "https://github.com/${GITHUB_USERNAME}/${REPO_NAME}.git"

echo ""
echo "Done: https://github.com/${GITHUB_USERNAME}/${REPO_NAME}"
echo "Future pushes: git push (you'll be prompted for credentials, or set up a credential helper / SSH key)."
