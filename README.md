# 🦁 Simba Intel

**Simba Intel** is an AI-powered virtual assistant built with **Django, Python, and Groq AI**. It provides real-time conversational AI capabilities, chat session management, and system monitoring through a modern web interface.

## ✨ Features

### 🤖 AI Chat Assistant

* Real-time AI conversations
* Streaming responses
* Multiple AI model support
* Context-aware responses with conversation memory

### 💬 Chat Management

* Create and manage chat sessions
* Rename conversations
* Pin important chats
* Persistent chat history

### 📊 System Monitoring

* CPU usage tracking
* RAM monitoring
* Disk usage monitoring
* Network statistics
* GPU monitoring support

### 🎨 User Experience

* Clean modern interface
* Fast response streaming
* Responsive design
* Session-based model selection

---

## 🛠️ Tech Stack

### Backend

* Python
* Django
* Gunicorn

### AI

* Groq API
* Llama Models

### Data Processing

* Pandas
* PDFPlumber
* Requests

### Monitoring

* Psutil
* GPUtil

### Database

* SQLite

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

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key
```

### 5. Run Migrations

```bash
python manage.py migrate
```

### 6. Start Development Server

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

* User Authentication
* Google Login
* User-specific Chat History
* PostgreSQL Support
* Voice Assistant Features
* File Search & Knowledge Base
* AI Agent Workflows

---

## 👨‍💻 Creator

**Dhruv Shah**

Simba Intel was built as a personal AI assistant project focused on intelligent conversations, productivity, and modern AI-powered workflows.
