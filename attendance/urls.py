from django.urls import path
from . import views

app_name = 'attendance'

urlpatterns = [
    path('upload/', views.upload_mdm, name='upload_mdm'),
    path('status/', views.mdm_status, name='mdm_status'),
    path('schedule/', views.schedule_index, name='schedule_index'),
    path('schedule/apply-all/', views.apply_all_normal, name='apply_all_normal'),
    path('schedule/update/', views.update_schedule, name='update_schedule'),
    path('schedule/requests/pending/', views.get_pending_requests, name='get_pending_requests'),
    path('schedule/requests/process/', views.process_request, name='process_request'),
]