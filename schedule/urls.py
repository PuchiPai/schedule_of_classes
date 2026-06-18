from django.urls import path
from . import views

app_name = 'schedule'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('group/<int:group_id>/', views.group_schedule_view, name='group_schedule'),
    path('teacher/<int:teacher_id>/', views.teacher_schedule_view, name='teacher_schedule'),
    path('room/<int:room_id>/', views.room_load_view, name='room_load'),

    path('reports/', views.reports_home_view, name='reports_home'),
    path('reports/chessboard/', views.multi_group_chessboard_view, name='multi_group_chessboard'),
    path('reports/attestation/', views.attestation_schedule_view, name='attestation_schedule'),
    path('reports/department/<int:department_id>/', views.department_teacher_plan_view, name='department_teacher_plan'),
    path('reports/rooms/', views.room_summary_view, name='room_summary'),

    # Новые URL
    path('schedule-table/', views.schedule_table_view, name='schedule_table'),
    path('teacher-assignments/', views.teacher_assignment_report_view, name='teacher_assignment_report'),
    path('teacher-workload/', views.teacher_workload_view, name='teacher_workload'),
    path('copy-schedule/', views.copy_schedule_view, name='copy_schedule'),
    path('reschedule/<int:entry_id>/', views.reschedule_entry_view, name='reschedule_entry'),
    path('report/group-workload/<int:group_id>/<int:semester_id>/', views.group_workload_report, name='group_workload_report'),
]