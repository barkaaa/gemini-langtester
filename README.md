# Gemini Langtester

Local FastAPI app for adaptive Japanese reading assessment. The backend serves the static frontend from `frontend/`.

## Local Deployment

PowerShell, recommended:

```powershell
.\scripts\run-local.ps1
```

Then open:

```text
http://127.0.0.1:8000
```

Use another port if needed:

```powershell
.\scripts\run-local.ps1 -Port 8080
```

## Manual Commands

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Set `GEMINI_API_KEY` in `.env` before starting the first assessment when using
AI Studio.

## Google Cloud Vertex AI

To use Gemini through Google Cloud instead of an AI Studio API key:

```powershell
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com
```

Then set these values in `.env`:

```dotenv
GEMINI_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=asia-northeast1
GEMINI_MODEL=gemini-3.5-flash
```

Start normally:

```powershell
.\scripts\run-local.ps1
```

## Troubleshooting

If starting an assessment returns `503` with `Gemini API returned HTTP 429`,
the local app is running but the Gemini project is rate-limited or out of
credits. For AI Studio, check the `GEMINI_API_KEY` and billing/quota status. For
Vertex AI, check the Google Cloud project billing status, IAM permissions, and
`GOOGLE_CLOUD_LOCATION`.

## Docker

```powershell
docker build -t gemini-langtester .
docker run --rm -p 8080:8080 --env-file .env gemini-langtester
```

Then open `http://127.0.0.1:8080`.
