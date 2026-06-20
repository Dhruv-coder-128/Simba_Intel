from django.contrib import admin
from django.urls import path
from chat import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.chat_home, name='home'),
    path('ask/', views.ask_ai, name='ask'),
    path('pin_session/<int:session_id>/', views.pin_session, name='pin_session'),
    path('delete_session/<int:session_id>/', views.delete_session, name='delete_session'),
    path('rename_session/<int:session_id>/', views.rename_session, name='rename_session'),
    path('ask_ai/', views.ask_ai, name='ask_ai'),
    path('update_model/', views.update_model_session, name='update_model'),
    path('system_stats/', views.system_stats, name='system_stats'),
    path("upload/", views.upload_file),
]