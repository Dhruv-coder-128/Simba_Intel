# 🦁 Simba Intel

**Simba Intel** is an AI-powered virtual assistant built with **Django** and **Python**. It provides real-time streaming conversations across multiple LLM providers, AI image generation, chat session management, file analysis, live web search, and system monitoring through a single web interface.

## ✨ Features

### 🤖 AI Chat Assistant

* Real-time streaming AI conversations (Groq and Mistral-backed models)
* Multiple, hot-swappable AI models via a provider-adapter layer (`chat/providers/`)
* Context-aware responses using per-session conversation history
* Automatic live web search augmentation for time-sensitive queries (Tavily)
* File upload + analysis (PDF, CSV, TXT, JPG/PNG via OCR)

### 🎨 AI Image Generation

* Prompt-to-image generation via Pollinations (Flux model)
* Automatic prompt enhancement and negative-prompt handling (kept server-side)
* Aspect ratio presets (1:1, 16:9, 9:16), download / copy-prompt / regenerate actions

### 💬 Chat Management

* Create and manage chat sessions
* Rename, pin, and delete conversations
* Persistent, per-user chat history (message tree groundwork for future branching)

### 🔐 Authentication

* Email/password auth and Google OAuth login (django-allauth)

### 📊 System Monitoring

* CPU / RAM / GPU / disk usage widgets (authenticated users only)

### 🎨 User Experience

* Cyberpunk-styled, responsive interface (desktop, tablet, mobile)
* Markdown + syntax-highlighted code blocks, voice input (browser speech recognition)

---

## 🛠️ Tech Stack

### Backend

* Python, Django, Gunicorn, Whitenoise

### AI Providers

* Groq API (Llama models)
* Mistral API (chat + vision)
* Pollinations (image generation)
* Tavily (web search augmentation)

### Data Processing

* Pandas, PDFPlumber, Pillow, pytesseract (OCR)

### Monitoring

* Psutil, GPUtil

### Database

* PostgreSQL (local dev and production — see [Installation](#-installation) and [Deployment](#-deployment)).

---

## 📂 Project Structure

```text
Simba_Intel/
│
├── chat/
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── migrations/
│
├── simba_web/
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│
├── templates/
├── static/
├── uploads/
│
├── manage.py
├── requirements.txt
└── README.md
```

---

## 🚀 Installation

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/Simba_Intel.git
cd Simba_Intel
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
```

Activate:

**Windows**

```bash
.venv\Scripts\activate
```

**Linux / macOS**

```bash
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```env
# Django
DEBUG=True
DJANGO_SECRET_KEY=generate-your-own-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1
SITE_ID=1
CSRF_TRUSTED_ORIGINS=http://localhost:8000

# Google OAuth (optional, for "Continue with Google"). allauth reads the
# Client ID/Secret from a SocialApp row, not these two directly - set them
# here and chat/migrations/0025_setup_google_socialapp.py creates/updates
# that row automatically on `manage.py migrate` (re-run
# `manage.py setup_google_oauth` after rotating either value). Get
# credentials from https://console.cloud.google.com/apis/credentials
# (authorized redirect URI: <your-domain>/accounts/google/login/callback/).
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret

# AI Providers
GROQ_API_KEY=your-groq-api-key
MISTRAL_API_KEY=your-mistral-api-key
TAVILY_API_KEY=your-tavily-api-key      # optional, enables live web search

# Email (for account verification / password reset) - sent via the Resend
# API, not SMTP. Get a key from https://resend.com/api-keys.
RESEND_API_KEY=your-resend-api-key

# Database - PostgreSQL only, no SQLite fallback. Either set DATABASE_URL
# directly, or leave it unset and use the POSTGRES_* vars below against a
# local Postgres instance (defaults match Postgres's own local conventions):
# DATABASE_URL=postgres://user:password@host:5432/dbname
POSTGRES_DB=simba_intel
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

**Never commit a real `.env`.** Always generate your own `DJANGO_SECRET_KEY` — the app refuses to start with `DEBUG=False` while the placeholder key from `.env.example` is still in use.

Pollinations image generation needs no API key.

### 5. Create the Database

Requires a local PostgreSQL server ([postgresql.org/download](https://www.postgresql.org/download/) or `choco install postgresql`/`brew install postgresql`). Create a database matching `POSTGRES_DB` above:

```bash
createdb simba_intel
```

### 6. Run Migrations

```bash
python manage.py migrate
```

### 7. Create an Admin User

```bash
python manage.py createsuperuser
```

### 8. Run Tests

```bash
python manage.py test
```

### 9. Start Development Server

```bash
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000
```

---

## 🌐 Deployment

The project can be deployed on:

* Render
* Railway
* VPS Servers
* Docker Environments

Example production command:

```bash
gunicorn simba_web.wsgi:application
```

---

## 🔒 Security Notes

* Never commit `.env` files.
* Keep API keys private.
* Store sensitive configuration in environment variables.
* Rotate API keys if they are exposed.

---

## 📈 Future Improvements

* pgvector-backed long-term memory (semantic recall across sessions)
* Message-tree schema for regeneration / edit-and-branch
* File Search & Knowledge Base
* AI Agent / tool-calling workflows
* Content Security Policy headers

---

## 👨‍💻 Creator

**Dhruv Shah**

Simba Intel was built as a personal AI assistant project focused on intelligent conversations, productivity, and modern AI-powered workflows.
