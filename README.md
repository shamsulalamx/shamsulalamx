# NBME Self-Assessment Suite

Static HTML/CSS/JavaScript app for generating and reviewing NBME-style self-assessment tests.

The app is designed for Netlify hosting. Netlify serves the frontend and runs the secure Gemini backend functions. User PDFs, generated tests, images, and metadata are stored in the user's Google Drive, not in Netlify.

## What Gets Deployed

- Frontend entry point: `index.html`
- Publish directory: repo root
- Build command: none
- Netlify Functions directory: `netlify/functions`

Netlify hosts only the app shell and backend functions. Google Drive remains the durable cross-device data store.

## Required Accounts

- GitHub account
- Netlify account
- Google account
- Google Cloud project with Google Drive API enabled
- Gemini API key from Google AI Studio or Google Cloud

## Upload To GitHub

1. Create a new GitHub repository.
2. Upload this project folder to the repository.
3. Make sure these files are included:
   - `index.html`
   - `netlify.toml`
   - `netlify/functions/_gemini.js`
   - `netlify/functions/gemini-tagging.js`
   - `netlify/functions/gemini-hint.js`
   - `netlify/functions/gemini-analysis.js`
   - `README.md`

Do not upload private API keys.

## Deploy On Netlify

1. Open Netlify.
2. Choose Add new site.
3. Choose Import an existing project.
4. Connect the GitHub repository.
5. Use these build settings:
   - Build command: leave blank
   - Publish directory: `.`
   - Functions directory: `netlify/functions`
6. Deploy the site.
7. Copy the deployed URL, for example:

```text
https://MY-NETLIFY-SITE.netlify.app
```

## Netlify Environment Variables

In Netlify, open:

```text
Site configuration -> Environment variables
```

Add:

```text
GEMINI_API_KEY=your Gemini API key
```

Redeploy after adding or changing this value.

The Gemini key must never be typed into the app, committed to GitHub, or placed in frontend JavaScript.

## Google Cloud Console Setup

Open Google Cloud Console and select the project used for this app.

### Enable Google Drive API

1. Go to APIs & Services.
2. Open Library.
3. Search for Google Drive API.
4. Enable it.

### OAuth Consent Screen

1. Go to APIs & Services -> OAuth consent screen.
2. Choose External unless this is restricted to a Google Workspace organization.
3. Add the required app name, support email, and developer contact email.
4. Add the Google account you will use under Test users if the app is still in testing mode.
5. Save.

### OAuth Client

1. Go to APIs & Services -> Credentials.
2. Create or edit an OAuth client ID.
3. Application type: Web application.
4. Add this Authorized JavaScript origin:

```text
https://MY-NETLIFY-SITE.netlify.app
```

5. Optional local development origins:

```text
http://localhost:8888
http://localhost:8080
```

6. Authorized redirect URI:

```text
Not required for the current Google Identity Services token flow.
```

The app uses the browser token client for Google Drive access. That flow requires Authorized JavaScript origins, not a redirect URI.

## Gemini Setup

1. Create a Gemini API key.
2. Add it to Netlify as `GEMINI_API_KEY`.
3. Redeploy the site.
4. Open the deployed app.
5. Open Settings.
6. Confirm the Gemini status says the backend is configured.

Gemini requests go only through:

```text
/.netlify/functions/gemini-tagging
/.netlify/functions/gemini-hint
/.netlify/functions/gemini-analysis
```

The browser does not send or store the Gemini API key.

## Google Drive Sync Across Devices

On the first device:

1. Open the deployed Netlify URL.
2. Open Settings.
3. Click Connect Drive.
4. Sign into the Google account that should own the app data.
5. Click Backup Now after generating or importing tests.

On another device:

1. Open the same deployed Netlify URL.
2. Open Settings.
3. Click Connect Drive.
4. Sign into the same Google account.
5. Click Restore Drive.

The app restores tests, folders, notes, history, metadata, and image references from Google Drive. Images are downloaded back into the browser's IndexedDB cache as needed.

## Local Development

Use Netlify local development when testing Gemini functions:

```bash
netlify dev
```

Netlify usually serves the app at:

```text
http://localhost:8888
```

For Drive testing from local development, add `http://localhost:8888` as an Authorized JavaScript origin in Google Cloud Console.

Opening `index.html` with `file://` is not supported for Drive or Gemini. Use the deployed HTTPS site or Netlify local dev.

## Redeploy Updates

1. Edit files locally.
2. Commit and push to GitHub.
3. Netlify automatically deploys the new commit.
4. If you changed environment variables, trigger a redeploy from Netlify.

## Required Settings Summary

Netlify:

- Publish directory: `.`
- Build command: blank
- Functions directory: `netlify/functions`
- Environment variable: `GEMINI_API_KEY`

Google Cloud:

- Enable Google Drive API.
- Create OAuth Web application client.
- Authorized JavaScript origin: `https://MY-NETLIFY-SITE.netlify.app`
- Optional local origins: `http://localhost:8888`, `http://localhost:8080`
- Authorized redirect URI: not required for the current token flow.

Gemini:

- Keep the API key only in Netlify as `GEMINI_API_KEY`.
- Do not place the key in `index.html`, localStorage, or Google Drive backups.
