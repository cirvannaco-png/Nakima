"""GitHub App manifest registration flow.

Two endpoints:

  GET /github/register
      Serves an HTML page that auto-submits the XO Nakima manifest to
      GitHub's "Create from manifest" form at github.com/settings/apps/new.
      The user must be logged in to GitHub; they see a single confirmation
      screen then GitHub redirects to /github/setup.

  GET /github/setup?code=<code>
      GitHub redirects here after the user approves the manifest.
      Exchanges the one-time code for credentials via the GitHub REST API,
      then displays the App ID, private key, and webhook secret so the
      operator can set them as Render environment variables.

Usage:
  1. Deploy this code to Render.
  2. Visit https://nakima.onrender.com/github/register while logged in to
     the cirvannaco-png GitHub account.
  3. Click through the GitHub confirmation page.
  4. Copy the three credentials from /github/setup into Render env vars:
       GITHUB_APP_ID          (numeric)
       GITHUB_PRIVATE_KEY     (the full PEM block, newlines as \\n or literal)
       GITHUB_WEBHOOK_SECRET  (the hex string)
  5. Redeploy the Render service to pick up the new env vars.
"""

import json
import logging

import httpx
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Manifest ──────────────────────────────────────────────────────────────────
_BASE_URL = "https://nakima.onrender.com"

_MANIFEST: dict = {
    "name": "XO Nakima",
    "url": _BASE_URL,
    "hook_attributes": {
        "url": f"{_BASE_URL}/github/webhook",
        "active": True,
    },
    "redirect_url": f"{_BASE_URL}/github/setup",
    "callback_urls": [f"{_BASE_URL}/github/setup"],
    "description": (
        "Multi-agent orchestration platform that plans, executes, and verifies code changes across GitHub repositories."
    ),
    "public": False,
    "default_events": [
        "create",
        "delete",
        "check_run",
        "check_suite",
        "installation",
        "installation_repositories",
        "issues",
        "issue_comment",
        "pull_request",
        "pull_request_review",
        "push",
        "status",
    ],
    "default_permissions": {
        "checks": "write",
        "contents": "read",
        "issues": "write",
        "metadata": "read",
        "pull_requests": "write",
        "statuses": "write",
        "workflows": "write",
    },
}

_MANIFEST_JSON = json.dumps(_MANIFEST)

# ── Registration page ─────────────────────────────────────────────────────────

_REGISTER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Register XO Nakima · GitHub App</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0d1117; color: #e6edf3;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh;
    }
    .card {
      background: #161b22; border: 1px solid #30363d;
      border-radius: 12px; padding: 2.5rem 3rem;
      max-width: 500px; width: 100%; text-align: center;
    }
    h1 { font-size: 1.5rem; margin-bottom: .5rem; }
    p  { color: #8b949e; margin-bottom: 1.5rem; line-height: 1.6; }
    .spinner {
      width: 40px; height: 40px; border: 3px solid #30363d;
      border-top-color: #58a6ff; border-radius: 50%;
      animation: spin .8s linear infinite; margin: 0 auto 1.5rem;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .badge {
      display: inline-block; background: #1f6feb33; color: #58a6ff;
      border: 1px solid #1f6feb; border-radius: 6px;
      font-size: .8rem; padding: .2rem .6rem; margin-bottom: 1.5rem;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <h1>Registering XO Nakima</h1>
    <span class="badge">GitHub App · manifest flow</span>
    <p>Redirecting to GitHub to create the app.<br>
       You will see a confirmation screen — click <strong>Create GitHub App</strong>.</p>
    <p style="font-size:.8rem; color:#6e7681;">
      You must be logged in as <code>cirvannaco-png</code>.
    </p>
  </div>
  <form id="f" method="post" action="https://github.com/settings/apps/new" hidden>
    <input name="manifest" value="{manifest_json}">
  </form>
  <script>
    // Auto-submit after a brief pause so the user sees the loading screen.
    setTimeout(() => document.getElementById("f").submit(), 800);
  </script>
</body>
</html>
"""


@router.get("/register", include_in_schema=False)
async def register_app() -> HTMLResponse:
    """Serve the manifest auto-submit page."""
    manifest_escaped = _MANIFEST_JSON.replace('"', "&quot;")
    return HTMLResponse(_REGISTER_HTML.replace("{manifest_json}", manifest_escaped))


# ── Setup callback ────────────────────────────────────────────────────────────

_SETUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>XO Nakima · App Credentials</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0d1117; color: #e6edf3; padding: 2rem;
    }
    h1 { font-size: 1.6rem; margin-bottom: .25rem; }
    .sub { color: #8b949e; margin-bottom: 2rem; }
    .banner {
      background: #3d1a1a; border: 1px solid #f85149;
      border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 2rem;
      color: #ffa198; font-size: .9rem;
    }
    .section { margin-bottom: 1.75rem; }
    label {
      display: block; font-size: .8rem; font-weight: 600;
      color: #8b949e; text-transform: uppercase; letter-spacing: .05em;
      margin-bottom: .4rem;
    }
    .value-wrap { position: relative; }
    pre, .mono {
      background: #161b22; border: 1px solid #30363d; border-radius: 6px;
      padding: .75rem 1rem; font-family: "SFMono-Regular", Consolas, monospace;
      font-size: .85rem; overflow-x: auto; white-space: pre-wrap;
      word-break: break-all;
    }
    .copy-btn {
      position: absolute; top: .4rem; right: .4rem;
      background: #21262d; border: 1px solid #30363d; color: #e6edf3;
      border-radius: 6px; padding: .3rem .75rem; cursor: pointer;
      font-size: .8rem;
    }
    .copy-btn:hover { background: #30363d; }
    .steps {
      background: #161b22; border: 1px solid #30363d;
      border-radius: 8px; padding: 1.25rem 1.5rem; margin-top: 2rem;
    }
    .steps h2 { font-size: 1rem; margin-bottom: .75rem; }
    ol { padding-left: 1.25rem; color: #c9d1d9; line-height: 1.9; }
    code {
      background: #21262d; border-radius: 4px;
      padding: .1em .35em; font-size: .85em;
    }
    .ok { color: #3fb950; }
  </style>
</head>
<body>
  <h1>&#x2705; XO Nakima · App Created</h1>
  <p class="sub">App ID <strong>{app_id}</strong> &mdash; slug <em>{slug}</em></p>

  <div class="banner">
    &#x26A0;&#xFE0F; <strong>Store these credentials now.</strong>
    This page will not show the private key or webhook secret again.
    Leaving without copying them means you will need to regenerate the key
    in the GitHub App settings.
  </div>

  <div class="section">
    <label>GITHUB_APP_ID</label>
    <div class="value-wrap">
      <pre id="app_id">{app_id}</pre>
      <button class="copy-btn" onclick="copy('app_id')">Copy</button>
    </div>
  </div>

  <div class="section">
    <label>GITHUB_WEBHOOK_SECRET</label>
    <div class="value-wrap">
      <pre id="wh_secret">{webhook_secret}</pre>
      <button class="copy-btn" onclick="copy('wh_secret')">Copy</button>
    </div>
  </div>

  <div class="section">
    <label>GITHUB_PRIVATE_KEY &mdash; paste the entire block including headers</label>
    <div class="value-wrap">
      <pre id="pem">{pem}</pre>
      <button class="copy-btn" onclick="copy('pem')">Copy</button>
    </div>
  </div>

  <div class="steps">
    <h2>Next steps</h2>
    <ol>
      <li>In <a href="https://dashboard.render.com" style="color:#58a6ff">Render</a>,
          open service <code>srv-d9dmdgu1a83c73b1cfr0</code> → <em>Environment</em>.</li>
      <li>Add <code>GITHUB_APP_ID</code>, <code>GITHUB_PRIVATE_KEY</code>,
          and <code>GITHUB_WEBHOOK_SECRET</code> using the values above.</li>
      <li>Also add <code>GITHUB_TOKEN</code> (a PAT with <em>Models: read</em>)
          for AI features.</li>
      <li>Click <strong>Save Changes</strong> — Render will redeploy automatically.</li>
      <li>
        <a href="https://github.com/apps/xo-nakima/installations/new"
           style="color:#58a6ff">
          Install the app on the repositories you want Nakima to analyse.
        </a>
      </li>
    </ol>
  </div>

  <script>
    function copy(id) {
      const el = document.getElementById(id);
      navigator.clipboard.writeText(el.innerText).then(() => {
        const btn = el.nextElementSibling;
        btn.textContent = "Copied ✓";
        btn.style.color = "#3fb950";
        setTimeout(() => { btn.textContent = "Copy"; btn.style.color = ""; }, 2000);
      });
    }
  </script>
</body>
</html>
"""

_ERROR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/><title>Setup Error · XO Nakima</title>
  <style>
    body {{ font-family: sans-serif; background:#0d1117; color:#e6edf3;
            display:flex; align-items:center; justify-content:center; min-height:100vh; }}
    .card {{ background:#161b22; border:1px solid #f85149; border-radius:12px;
             padding:2.5rem 3rem; max-width:500px; text-align:center; }}
    h1 {{ color:#f85149; margin-bottom:1rem; }}
    pre {{ background:#0d1117; border-radius:6px; padding:1rem;
           font-size:.8rem; text-align:left; white-space:pre-wrap; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>&#x274C; Setup failed</h1>
    <p style="color:#8b949e;margin-bottom:1rem;">{message}</p>
    <pre>{detail}</pre>
    <p style="margin-top:1.5rem;font-size:.85rem;color:#8b949e;">
      Return to <a href="/github/register" style="color:#58a6ff">/github/register</a>
      and try again.
    </p>
  </div>
</body>
</html>
"""


@router.get("/setup", include_in_schema=False)
async def setup_callback(code: str = "") -> HTMLResponse:
    """Exchange the one-time GitHub manifest code for app credentials."""
    if not code:
        return HTMLResponse(
            _ERROR_HTML.format(
                message="No <code>code</code> parameter received.",
                detail="GitHub did not redirect here with a code. Make sure you started\n"
                "from /github/register and completed the GitHub confirmation page.",
            ),
            status_code=400,
        )

    logger.info("github_app_setup: exchanging manifest code for credentials")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.github.com/app-manifests/{code}/conversions",
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except httpx.RequestError as exc:
        logger.error(f"github_app_setup: network error: {exc}")
        return HTMLResponse(
            _ERROR_HTML.format(
                message="Network error contacting GitHub.",
                detail=str(exc),
            ),
            status_code=502,
        )

    if resp.status_code != 201:
        logger.error(f"github_app_setup: GitHub returned {resp.status_code}: {resp.text}")
        return HTMLResponse(
            _ERROR_HTML.format(
                message=f"GitHub returned HTTP {resp.status_code}.",
                detail=resp.text[:1000],
            ),
            status_code=resp.status_code,
        )

    data = resp.json()
    app_id = data.get("id", "")
    slug = data.get("slug", "")
    pem = data.get("pem", "").strip()
    webhook_secret = data.get("webhook_secret", "")

    logger.info(f"github_app_setup: app created successfully — id={app_id} slug={slug}")

    return HTMLResponse(
        _SETUP_HTML.format(
            app_id=app_id,
            slug=slug,
            pem=pem,
            webhook_secret=webhook_secret,
        )
    )
