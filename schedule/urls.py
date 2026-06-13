from django.urls import path
from . import views

app_name = 'schedule'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('group/<int:group_id>/', views.group_schedule_view, name='group_schedule'),
    path('teacher/<int:teacher_id>/', views.teacher_schedule_view, name='teacher_schedule'),
    path('room/<int:room_id>/', views.room_load_view, name='room_load'),
]