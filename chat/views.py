
import base64
import os
import time
import uuid
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth.decorators import login_required
import psutil

try:
    import GPUtil
    GPUtil_AVAILABLE = True
except ImportError:
    GPUtil_AVAILABLE = False

from chat.models import ChatSession, ChatMessage, UserProfile
from chat.services.ai_router import chat_stream, vision as ai_vision
from chat.services.image_router import generate_image
from chat.services.memory import get_conversation_history, build_messages, SYSTEM_PROMPT
from chat.services.model_registry import list_available_models, get_model_config
from chat.utils.logger import SimbaLogger

from chat.file_analyzer import analyze_file


logger = SimbaLogger()

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".csv", ".txt"} | ALLOWED_IMAGE_EXTENSIONS
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_ATTACHMENTS_PER_MESSAGE = 6

IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _validate_attachment(attachment):
    """Returns (safe_name, ext, error_message_or_None)."""
    if attachment.size > MAX_UPLOAD_SIZE_BYTES:
        return None, None, "File too large (max 10MB)"
    safe_name = os.path.basename(attachment.name)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return None, None, "Unsupported file type"
    return safe_name, ext, None


def _extract_attachment_text(attachment, safe_name, ext):
    """Save an uploaded file transiently, run it through file_analyzer, then delete it."""
    save_dir = os.path.join(settings.BASE_DIR, "uploads")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{uuid.uuid4().hex}{ext}")
    with open(save_path, "wb+") as f:
        for chunk in attachment.chunks():
            f.write(chunk)
    try:
        return analyze_file(save_path)
    finally:
        try:
            os.remove(save_path)
        except OSError:
            pass


def _get_tavily_search(query: str):
    try:
        from tavily import TavilyClient
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            return None
        client = TavilyClient(api_key=tavily_api_key)
        response = client.search(query=query, search_depth="advanced", max_results=5)
        return response.get("results", [])
    except Exception as e:
        logger.log_request(
            provider="tavily",
            latency=0,
            prompt_length=len(query),
            response_length=0,
            error=str(e)
        )
        return None


def _is_search_query(query: str) -> bool:
    search_keywords = ["latest", "today", "news", "search", "current", "price", "weather", "now", "recent", "stock", "market"]
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in search_keywords)


@login_required
def chat_home(request):
    profile = UserProfile.get_or_create_for(request.user)
    sessions = ChatSession.objects.filter(user=request.user).order_by('-is_pinned', '-id')
    session_id = request.GET.get('session')
    messages = []
    current_session = None
    if session_id and session_id not in ["null", "None", ""]:
        try:
            current_session = get_object_or_404(ChatSession, id=session_id, user=request.user)
            messages = ChatMessage.objects.filter(session=current_session).order_by('timestamp')
        except Exception:
            current_session = None
    selected_model = request.session.get("selected_model", profile.default_model)
    models = list_available_models()
    return render(request, 'chat.html', {
        'sessions': sessions,
        'messages': messages,
        'current_session': current_session,
        'selected_model': selected_model,
        'models': models,
        'profile': profile,
    })


@login_required
def profile_settings(request):
    profile = UserProfile.get_or_create_for(request.user)
    valid_model_ids = {m['id'] for m in list_available_models()}
    valid_themes = {choice[0] for choice in UserProfile.THEME_CHOICES}

    if request.method == "POST":
        display_name = request.POST.get('display_name', '').strip()[:100]
        default_model = request.POST.get('default_model', '').strip()
        theme = request.POST.get('theme', '').strip()

        profile.display_name = display_name
        if default_model in valid_model_ids:
            profile.default_model = default_model
        if theme in valid_themes:
            profile.theme = theme
        profile.memory_enabled = request.POST.get('memory_enabled') == 'on'
        profile.notifications_enabled = request.POST.get('notifications_enabled') == 'on'
        profile.save()
        return redirect('profile_settings')

    return render(request, 'profile.html', {
        'profile': profile,
        'models': list_available_models(),
        'theme_choices': UserProfile.THEME_CHOICES,
    })


@login_required
def ask_ai(request):
    if request.method == "POST":
        user_query = request.POST.get('query', '').strip()
        model_id = request.POST.get('model_id', 'cyber-max')
        session_id = request.POST.get('session_id')
        attachments = request.FILES.getlist('attachment')
        request.session["selected_model"] = model_id
        request.session.modified = True
        if not user_query and not attachments:
            return JsonResponse({"response": "Query cannot be empty"}, status=400)
        if len(attachments) > MAX_ATTACHMENTS_PER_MESSAGE:
            return JsonResponse(
                {"type": "error", "message": f"Too many attachments (max {MAX_ATTACHMENTS_PER_MESSAGE})"},
                status=400
            )
        try:
            first_name = attachments[0].name[:20] if attachments else ""
            session_title = user_query[:30] if user_query else (
                f"Attachment: {first_name}" if attachments else "New Chat"
            )
            if not session_id or session_id in ["null", "None", ""]:
                session = ChatSession.objects.create(user=request.user, title=session_title)
            else:
                session = ChatSession.objects.get(id=session_id, user=request.user)

            model_config = get_model_config(model_id)

            if attachments:
                validated = []  # list of (attachment, safe_name, ext)
                for att in attachments:
                    safe_name, ext, attach_error = _validate_attachment(att)
                    if attach_error:
                        attach_response = JsonResponse(
                            {"type": "error", "message": f"{att.name}: {attach_error}"}, status=400
                        )
                        attach_response["X-Session-ID"] = str(session.id)
                        return attach_response
                    validated.append((att, safe_name, ext))

                image_files = [v for v in validated if v[2] in ALLOWED_IMAGE_EXTENSIONS]
                doc_files = [v for v in validated if v[2] not in ALLOWED_IMAGE_EXTENSIONS]

                if image_files and model_config.supports_vision:
                    # True vision: send every image straight to a vision-capable model
                    # in a single multi-image message.
                    try:
                        text_parts = []
                        for att, safe_name, ext in doc_files:
                            extracted = _extract_attachment_text(att, safe_name, ext)
                            text_parts.append(f"--- Attached file: {safe_name} ---\n{extracted}\n--- End attachment ---")
                        text_parts.append(user_query or (
                            "Describe this image." if len(image_files) == 1 else "Describe these images."
                        ))

                        content = [{"type": "text", "text": "\n\n".join(text_parts)}]
                        image_previews = []
                        filenames = []
                        for att, safe_name, ext in image_files:
                            image_bytes = att.read()
                            mime = IMAGE_MIME_TYPES.get(ext, "image/jpeg")
                            data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
                            content.append({"type": "image_url", "image_url": {"url": data_uri}})
                            image_previews.append(data_uri)
                            filenames.append(safe_name)

                        vision_messages = [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": content}
                        ]
                        start_time = time.time()
                        vision_text = ai_vision(model_id, vision_messages)
                        latency = round(time.time() - start_time, 2)

                        display_query = user_query or f"[{len(image_files)} image(s): {', '.join(filenames)}]"
                        ChatMessage.objects.create(
                            session=session,
                            user_query=display_query,
                            ai_response=vision_text,
                            latency=latency,
                            extra_data={
                                "type": "vision",
                                "filenames": filenames,
                                "image_previews": image_previews,
                                # kept for backward compatibility with older rendered history
                                "filename": filenames[0],
                                "image_preview": image_previews[0],
                            }
                        )
                        logger.log_request(
                            provider=model_config.provider,
                            latency=latency,
                            prompt_length=len(user_query),
                            response_length=len(vision_text)
                        )
                        vision_response = JsonResponse({
                            "type": "vision",
                            "response": vision_text,
                            "image_previews": image_previews,
                            "filenames": filenames
                        })
                        vision_response["X-Session-ID"] = str(session.id)
                        return vision_response
                    except Exception as e:
                        logger.log_request(
                            provider=model_config.provider,
                            latency=0,
                            prompt_length=len(user_query),
                            response_length=0,
                            error=str(e)
                        )
                        vision_error = JsonResponse({
                            "type": "error",
                            "message": "Couldn't analyze that image. Please try again."
                        })
                        vision_error["X-Session-ID"] = str(session.id)
                        return vision_error
                else:
                    # No vision support (or no images attached): extract text from every
                    # attachment (OCR for images, direct extraction for documents) and
                    # fold it into the conversation as context for the normal chat flow.
                    extracted_blocks = []
                    for att, safe_name, ext in validated:
                        extracted = _extract_attachment_text(att, safe_name, ext)
                        extracted_blocks.append(f"--- Attached file: {safe_name} ---\n{extracted}\n--- End attachment ---")
                    context_block = "\n\n".join(extracted_blocks)
                    user_query = f"{context_block}\n\n{user_query}" if user_query else context_block

            if model_config.supports_image_gen:
                # Handle image generation
                try:
                    seed = request.POST.get('seed')
                    aspect_ratio = request.POST.get('aspect_ratio', '1:1')
                    if seed and seed.strip():
                        seed = int(seed.strip())
                    else:
                        seed = None
                    result = generate_image(user_query, seed, aspect_ratio)
                    
                    if not result.get("success", False):
                        error_response = JsonResponse({
                            "type": "error",
                            "message": result.get(
                                "message",
                                result.get("error", "Image generation failed.")
                            )
                        })
                        error_response["X-Session-ID"] = str(session.id)
                        return error_response

                    # Save chat message with image
                    if session:
                        result.setdefault("generation_time", 0)
                        ChatMessage.objects.create(
                            session=session,
                            user_query=user_query,
                            ai_response="",
                            latency=result.get("generation_time", 0),
                            extra_data={
                                "type": "image",
                                "image_url": result["image_url"],
                                "model_used": result["model_used"],
                                "prompt": result["prompt"],
                                "width": result["width"],
                                "height": result["height"],
                                "generation_time": result.get("generation_time", 0)
                            }
                        )

                    image_response = JsonResponse({
                        "success": True,
                        "type": "image",
                        "url": result["image_url"],
                        "model_used": result["model_used"],
                        "prompt": result["prompt"],
                        "width": result["width"],
                        "height": result["height"],
                        "generation_time": result.get("generation_time", 0)
                    })
                    image_response["X-Session-ID"] = str(session.id)
                    return image_response
                except Exception as e:
                    logger.log_request(
                        provider="pollinations",
                        latency=0,
                        prompt_length=len(user_query),
                        response_length=0,
                        error=str(e)
                    )
                    error_response = JsonResponse({
                        "type": "error",
                        "message": "Image generation failed. Please try again."
                    })
                    error_response["X-Session-ID"] = str(session.id)
                    return error_response
            
            # Regular chat
            history = get_conversation_history(session)
            messages = build_messages(user_query, history)
            if _is_search_query(user_query):
                search_results = _get_tavily_search(user_query)
                if search_results:
                    context_str = "\n\n".join([f"- {result['title']}: {result['content']}" for result in search_results])
                    augmented_query = f"{user_query}\n\nRelevant search results:\n{context_str}"
                    messages[-1]['content'] = augmented_query
            
            def stream_generator():
                full_response = ""
                start_time = time.time()
                try:
                    for token in chat_stream(model_id, messages):
                        full_response += token
                        yield token
                except Exception as e:
                    logger.log_request(
                        provider=model_config.provider,
                        latency=time.time() - start_time,
                        prompt_length=len(user_query),
                        response_length=len(full_response),
                        error=str(e)
                    )
                    yield f"\n\nError: {str(e)}"
                else:
                    latency = round(time.time() - start_time, 2)
                    if full_response.strip():
                        ChatMessage.objects.create(
                            session=session,
                            user_query=user_query,
                            ai_response=full_response,
                            latency=latency
                        )
                    logger.log_request(
                        provider=model_config.provider,
                        latency=latency,
                        prompt_length=len(user_query),
                        response_length=len(full_response)
                    )
            response = StreamingHttpResponse(stream_generator(), content_type="text/plain")
            response["X-Session-ID"] = str(session.id)
            return response
        except Exception as e:
            logger.log_request(
                provider=model_id,
                latency=0,
                prompt_length=len(user_query),
                response_length=0,
                error=str(e)
            )
            return JsonResponse({"response": "Something went wrong. Please try again."}, status=500)
    return JsonResponse({"error": "Invalid request"}, status=400)


@login_required
def delete_session(request, session_id):
    if request.method == "POST":
        get_object_or_404(ChatSession, id=session_id, user=request.user).delete()
        return JsonResponse({"status": "success"})


@login_required
def rename_session(request, session_id):
    if request.method == "POST":
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        session.title = request.POST.get('title')
        session.save()
        return JsonResponse({"status": "success"})


@login_required
def pin_session(request, session_id):
    if request.method == "POST":
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        session.is_pinned = not session.is_pinned
        session.save()
        return JsonResponse({"status": "success"})


@login_required
def system_stats(request):
    try:
        gpu_usage = 0.0
        if GPUtil_AVAILABLE:
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu_usage = gpus[0].load * 100
    except Exception:
        gpu_usage = 0.0
    data = {
        "cpu": psutil.cpu_percent(interval=0.1),
        "ram": psutil.virtual_memory().percent,
        "gpu": round(gpu_usage, 1),
        "disk": psutil.disk_usage('/').percent
    }
    return JsonResponse(data)


@login_required
def upload_file(request):
    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return JsonResponse({"error": "No file uploaded"})

        safe_name, ext, error = _validate_attachment(uploaded_file)
        if error:
            return JsonResponse({"error": error}, status=400)

        result = _extract_attachment_text(uploaded_file, safe_name, ext)
        return JsonResponse({"analysis": result})
    return JsonResponse({"error": "Invalid request"})


@login_required
def update_model_session(request):
    if request.method == "GET":
        model_id = request.GET.get('model_id')
        if model_id:
            request.session['selected_model'] = model_id
            request.session.modified = True
            return JsonResponse({
                "status": "success",
                "active_model": model_id
            })
    return JsonResponse({"status": "failed"}, status=400)
