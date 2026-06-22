import json
import time
import requests
import psutil
import os
from dotenv import load_dotenv
try:
    import GPUtil
    GPUtil_AVAILABLE = True
except ImportError:
    GPUtil_AVAILABLE = False
    GPUtil = None
import os
import pandas as pd
import pdfplumber

from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.contrib.auth.decorators import login_required
from groq import Groq

from chat.file_analyzer import analyze_file
from .models import ChatSession, ChatMessage

# =============================================================================
# CONFIGURATION
# =============================================================================

# Groq API Client
load_dotenv()
client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)

# System Prompt for Simba
SYSTEM_PROMPT = (
    "You are Simba, a professional female virtual assistant created by Dhruv.\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "IDENTITY & CORE VALUES\n"
    "═══════════════════════════════════════════════════════════\n"
    "• Name: Simba\n"
    "• Creator: Dhruv\n"
    "• Role: Intelligent, professional virtual assistant\n"
    "• Personality: Friendly, helpful, confident, and respectful\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "COMMUNICATION GUIDELINES\n"
    "═══════════════════════════════════════════════════════════\n"
    "• Use clear, concise, and professional language\n"
    "• Adapt tone based on context (formal for business, friendly for casual)\n"
    "• Be empathetic and understanding in responses\n"
    "• Avoid jargon unless explaining technical topics\n"
    "• Use proper grammar and punctuation\n"
    "• Keep responses focused and on-topic\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "CODING & TECHNICAL TASKS\n"
    "═══════════════════════════════════════════════════════════\n"
    "• Write clean, production-ready, well-documented code\n"
    "• Follow best practices and design patterns\n"
    "• Include error handling and edge cases\n"
    "• Add meaningful comments explaining complex logic\n"
    "• Optimize for performance and readability\n"
    "• Suggest improvements and alternative approaches\n"
    "• Explain code functionality when requested\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "PROBLEM-SOLVING APPROACH\n"
    "═══════════════════════════════════════════════════════════\n"
    "• Break complex problems into smaller, manageable steps\n"
    "• Provide step-by-step explanations\n"
    "• Offer multiple solutions when applicable\n"
    "• Highlight pros and cons of different approaches\n"
    "• Verify understanding before proceeding\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "KNOWLEDGE & ACCURACY\n"
    "═══════════════════════════════════════════════════════════\n"
    "• Provide accurate, fact-based information\n"
    "• Cite sources when sharing factual data (if known)\n"
    "• Distinguish between facts and opinions\n"
    "• If unsure: Acknowledge limitations honestly\n"
    "• Offer related information that might be helpful\n"
    "• Suggest where to find more reliable information\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "SAFETY & ETHICS\n"
    "═══════════════════════════════════════════════════════════\n"
    "• Do not provide harmful, illegal, or dangerous information\n"
    "• Respect privacy and confidentiality\n"
    "• Avoid bias and discrimination\n"
    "• Promote positive and constructive interactions\n"
    "• Never impersonate other AI systems or companies\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "RESPONSE HANDLING SCENARIOS\n"
    "═══════════════════════════════════════════════════════════\n"
    "• General Questions: Provide clear, direct answers with context\n"
    "• Technical Questions: Give detailed explanations with examples\n"
    "• Creative Tasks: Be imaginative while maintaining quality\n"
    "• Debugging: Identify root cause and provide fix with explanation\n"
    "• Learning Requests: Teach concepts progressively (basic → advanced)\n"
    "• Opinion Questions: Present balanced viewpoints with reasoning\n"
    "• Unknown Topics: Be honest, suggest alternatives, offer to help differently\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "IDENTITY PROTECTION\n"
    "═══════════════════════════════════════════════════════════\n"
    "• If asked about your name: \"I am Simba\"\n"
    "• If asked about your creator: \"I was created by Dhruv\"\n"
    "• Never mention other AI company names (OpenAI, Google, Anthropic, etc.)\n"
    "• Stay in character as Simba in all interactions\n"
    "\n"
    "═══════════════════════════════════════════════════════════\n"
    "GOAL\n"
    "═══════════════════════════════════════════════════════════\n"
    "Your primary goal is to assist users effectively, provide accurate information,\n"
    "write high-quality code, and create a positive user experience while\n"
    "maintaining your identity as Simba, created by Dhruv.\n"
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_memory_context(session):
    """Retrieve recent conversation history for context."""
    messages = ChatMessage.objects.filter(
        session=session
    ).order_by('-timestamp')[:6]

    context = ""
    for m in reversed(messages):
        context += f"User: {m.user_query}\n"
        context += f"Simba: {m.ai_response}\n"

    return context


def analyze_file(path):
    """Analyze uploaded file content based on file type."""
    if path.endswith(".txt"):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        return text[:2000]

    if path.endswith(".csv"):
        df = pd.read_csv(path)
        return f"""
CSV ANALYSIS
Rows: {df.shape[0]}
Columns: {df.shape[1]}
Columns:
{list(df.columns)}
Preview:
{df.head().to_string()}
"""

    if path.endswith(".pdf"):
        text = ""
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text
        return text[:2000]

    return "Unsupported file type"


# =============================================================================
# API ENDPOINTS
# =============================================================================

def update_model_session(request):
    """Update the selected model in user session."""
    if request.method == "GET":
        model_choice = request.GET.get('model')
        if model_choice:
            request.session['selected_model'] = model_choice
            request.session.modified = True
            return JsonResponse({
                "status": "success",
                "active_model": model_choice
            })
    return JsonResponse({"status": "failed"}, status=400)


@login_required
def chat_home(request):
    """Render chat home page with session and message history."""
    sessions = ChatSession.objects.filter(user=request.user).order_by('-is_pinned', '-id')
    session_id = request.GET.get('session')
    messages = []
    current_session = None
    
    if session_id and session_id not in ["null", "None", ""]:
        try:
            current_session = get_object_or_404(ChatSession, id=session_id, user=request.user)
            messages = ChatMessage.objects.filter(
                session=current_session
            ).order_by('timestamp')
        except:
            current_session = None
    
    selected_model = request.session.get("selected_model", "offline")

    return render(request, 'chat.html', {
        'sessions': sessions,
        'messages': messages,
        'current_session': current_session,
        'selected_model': selected_model
    })


# ---------------- ASK AI ----------------

@login_required
def ask_ai(request):
    """Process AI chat request with model selection and streaming response."""
    if request.method == "POST":
        user_query = request.POST.get('query', '').strip()
        model_choice = request.POST.get('model_choice', 'offline')
        session_id = request.POST.get('session_id')

        request.session["selected_model"] = model_choice
        request.session.modified = True

        if not user_query:
            return JsonResponse({"response": "Query cannot be empty"}, status=400)

        try:
            # Create or get chat session
            if not session_id or session_id in ["null", "None", ""]:
                session = ChatSession.objects.create(user=request.user, title=user_query[:30])
            else:
                session = ChatSession.objects.get(id=session_id, user=request.user)

            memory = get_memory_context(session)
            prompt = f"{SYSTEM_PROMPT}\n\nConversation Memory:\n{memory}\n\nUser: {user_query}\nSimba:"

            def stream_generator():
                full_response = ""
                start_time = time.time()

                try:
                    # OFFLINE (Ollama)
                    if model_choice == "offline":
                        res = requests.post(
                            "http://localhost:11434/api/generate",
                            json={"model": "qwen2.5-coder:3b", "prompt": prompt, "stream": True},
                            stream=True, timeout=120
                        )
                        for line in res.iter_lines():
                            if line:
                                chunk = json.loads(line)    
                                token = chunk.get("response", "")
                                full_response += token
                                yield token

                    # GROQ (Llama)
                    elif model_choice == "groq":
                        stream = client.chat.completions.create(
                            model="meta-llama/llama-4-scout-17b-16e-instruct", 
                            messages=[{"role": "user", "content": prompt}],
                            stream=True
                        )
                        for chunk in stream:
                            if chunk.choices[0].delta.content:
                                token = chunk.choices[0].delta.content
                                full_response += token
                                yield token

                    # GROQ2 (Alternative)
                    elif model_choice == "groq2":
                        stream = client.chat.completions.create(
                            model="groq/compound-mini",
                            messages=[{"role": "user", "content": prompt}],
                            stream=True
                        )
                        for chunk in stream:
                            if chunk.choices[0].delta.content:
                                token = chunk.choices[0].delta.content
                                full_response += token
                                yield token

                except Exception as e:
                    yield f"\n\nSIMBA_CONNECTION_ERROR: {str(e)}"

                # Save message to database
                if full_response.strip():
                    latency = round(time.time() - start_time, 2)
                    ChatMessage.objects.create(
                        session=session, user_query=user_query,
                        ai_response=full_response, latency=latency
                    )

            response = StreamingHttpResponse(stream_generator(), content_type="text/plain")
            response["X-Session-ID"] = str(session.id)
            return response

        except Exception as e:
            return JsonResponse({"response": f"Backend Error: {str(e)}"}, status=500)

    return JsonResponse({"error": "Invalid request"}, status=400)


# =============================================================================
# SESSION MANAGEMENT ENDPOINTS
# =============================================================================

@login_required
def delete_session(request, session_id):
    """Delete a chat session."""
    if request.method == "POST":
        get_object_or_404(ChatSession, id=session_id, user=request.user).delete()
        return JsonResponse({"status": "success"})


@login_required
def rename_session(request, session_id):
    """Rename a chat session."""
    if request.method == "POST":
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        session.title = request.POST.get('title')
        session.save()
        return JsonResponse({"status": "success"})


@login_required
def pin_session(request, session_id):
    """Toggle pin status of a chat session."""
    if request.method == "POST":
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        session.is_pinned = not session.is_pinned
        session.save()
        return JsonResponse({"status": "success"})


# =============================================================================
# SYSTEM MONITORING ENDPOINTS
# =============================================================================

def system_stats(request):
    """Return current system resource usage statistics."""
    try:
        if GPUtil_AVAILABLE:
            gpus = GPUtil.getGPUs()
            dgpu_usage = gpus[0].load * 100 if gpus else 0
        else:
            # Alternative method to get GPU info using nvidia-ml-py or just set to 0
            dgpu_usage = 0
    except Exception:
        dgpu_usage = 0

    net = psutil.net_io_counters()
    net_usage = (net.bytes_sent + net.bytes_recv) / 1024 / 1024 % 100

    data = {
        "cpu": psutil.cpu_percent(interval=0.1),
        "ram": psutil.virtual_memory().percent,
        "dgpu": round(dgpu_usage, 1),
        "igpu": psutil.cpu_percent() * 0.5,
        "disk": psutil.disk_usage('/').percent,
        "net": round(net_usage, 1)
    }
    return JsonResponse(data)


def upload_file(request):
    """Handle file upload and analysis."""
    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return JsonResponse({"error": "No file uploaded"})
        
        save_path = os.path.join(settings.BASE_DIR, "uploads", uploaded_file.name)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        with open(save_path, "wb+") as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)
        
        result = analyze_file(save_path)
        return JsonResponse({"analysis": result})
    
    return JsonResponse({"error": "Invalid request"})