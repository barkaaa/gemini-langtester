# Gemini Langtester

Adaptive Japanese reading assessment powered by FastAPI, a static browser UI,
and Gemini on Google Cloud Vertex AI.

The app generates JLPT-style reading questions, measures passage difficulty
locally, adapts the next question level, shows per-question timing, and reveals
the correct answer when the user is wrong.

Live demo:

```text
https://gemini-langtester-740802225235.asia-northeast1.run.app
```

## English

### Features

- Adaptive Japanese reading test for JLPT-like levels N5 to N1.
- Gemini-generated passages, questions, and answer choices.
- Local difficulty measurement, independent from the model's self-rating.
- Shuffled answer choices so the correct answer is not always A.
- Immediate feedback, correct-answer reveal, and per-question timer.
- Vertex AI support for Google Cloud deployment.

### Local Run

PowerShell, recommended:

```powershell
.\scripts\run-local.ps1
```

Open:

```text
http://127.0.0.1:8000
```

Use another port if needed:

```powershell
.\scripts\run-local.ps1 -Port 8080
```

### Vertex AI Setup

```powershell
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Create `.env`:

```dotenv
GEMINI_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=asia-northeast1
GEMINI_MODEL=gemini-3.5-flash
```

### Cloud Run Deploy

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com

gcloud run deploy gemini-langtester `
  --source . `
  --project YOUR_PROJECT_ID `
  --region asia-northeast1 `
  --allow-unauthenticated `
  "--set-env-vars=GEMINI_PROVIDER=vertex,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,GOOGLE_CLOUD_LOCATION=asia-northeast1,GEMINI_MODEL=gemini-3.5-flash"
```

### Docker

```powershell
docker build -t gemini-langtester .
docker run --rm -p 8080:8080 --env-file .env gemini-langtester
```

Open `http://127.0.0.1:8080`.

### Troubleshooting

- `HTTP 429 RESOURCE_EXHAUSTED`: check billing, quota, and model availability.
- `HTTP 404 model not found`: confirm `GEMINI_MODEL` is available in `GOOGLE_CLOUD_LOCATION`.
- Cloud Run cannot call Vertex AI: grant the runtime service account `roles/aiplatform.user`.
- PowerShell env var issue: wrap the whole `--set-env-vars=...` argument in quotes.

## 日本語

### 概要

Gemini Langtester は、日本語読解力を測定する適応型テストアプリです。
FastAPI バックエンド、静的フロントエンド、Google Cloud Vertex AI の Gemini を使います。

### 主な機能

- JLPT N5 から N1 相当の日本語読解テスト。
- Gemini による本文、設問、選択肢の生成。
- モデルの自己評価とは別に、ローカルエンジンで難易度を測定。
- 選択肢をシャッフルし、正解が常に A にならないように調整。
- 各問題の解答時間を表示。
- 誤答時に正解の選択肢と本文を表示。
- Google Cloud Vertex AI と Cloud Run に対応。

### ローカル起動

PowerShell で実行します。

```powershell
.\scripts\run-local.ps1
```

ブラウザで開きます。

```text
http://127.0.0.1:8000
```

ポートを変える場合:

```powershell
.\scripts\run-local.ps1 -Port 8080
```

### Vertex AI の設定

```powershell
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

`.env` を作成します。

```dotenv
GEMINI_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=asia-northeast1
GEMINI_MODEL=gemini-3.5-flash
```

### Cloud Run へのデプロイ

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com

gcloud run deploy gemini-langtester `
  --source . `
  --project YOUR_PROJECT_ID `
  --region asia-northeast1 `
  --allow-unauthenticated `
  "--set-env-vars=GEMINI_PROVIDER=vertex,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,GOOGLE_CLOUD_LOCATION=asia-northeast1,GEMINI_MODEL=gemini-3.5-flash"
```

### トラブルシューティング

- `HTTP 429 RESOURCE_EXHAUSTED`: 課金、クォータ、モデル利用可否を確認してください。
- `HTTP 404 model not found`: モデルが指定リージョンで利用可能か確認してください。
- Cloud Run から Vertex AI を呼べない場合: 実行サービスアカウントに `roles/aiplatform.user` を付与してください。
- PowerShell では `--set-env-vars=...` 全体を引用符で囲んでください。

## 中文

### 项目简介

Gemini Langtester 是一个日语阅读能力自适应测评应用。后端使用 FastAPI，
前端是静态页面，题目生成使用 Google Cloud Vertex AI 上的 Gemini。

### 功能

- 面向 JLPT N5 到 N1 的日语阅读测评。
- Gemini 生成文章、题目和选择项。
- 本地难度测量，不依赖模型自评。
- 后端随机打乱选项，避免正确答案总是 A。
- 每题计时，提交后显示用时。
- 答错时显示正确选项和正确答案文本。
- 支持本地运行、Docker、Cloud Run 部署。

### 本地启动

推荐 PowerShell：

```powershell
.\scripts\run-local.ps1
```

打开：

```text
http://127.0.0.1:8000
```

如果端口被占用：

```powershell
.\scripts\run-local.ps1 -Port 8080
```

### Vertex AI 配置

```powershell
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

创建 `.env`：

```dotenv
GEMINI_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=asia-northeast1
GEMINI_MODEL=gemini-3.5-flash
```

### Cloud Run 部署

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com

gcloud run deploy gemini-langtester `
  --source . `
  --project YOUR_PROJECT_ID `
  --region asia-northeast1 `
  --allow-unauthenticated `
  "--set-env-vars=GEMINI_PROVIDER=vertex,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,GOOGLE_CLOUD_LOCATION=asia-northeast1,GEMINI_MODEL=gemini-3.5-flash"
```

### 常见问题

- `HTTP 429 RESOURCE_EXHAUSTED`：检查账单、配额和模型可用性。
- `HTTP 404 model not found`：确认模型在指定区域可用。
- Cloud Run 无法调用 Vertex AI：给运行服务账号授予 `roles/aiplatform.user`。
- PowerShell 下设置多个环境变量时，要把整个 `--set-env-vars=...` 参数放进引号。
