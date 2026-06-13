from django.shortcuts import render, get_object_or_404
from django.db.models import Count

from .models import StudentGroup, Department, Teacher, Room
from .services import (
    get_group_schedule,
    get_teacher_schedule,
    get_room_load,
    get_attestation_schedule,
    get_department_teacher_plan,
    get_department_teacher_plan_rows,
    get_multi_group_chessboard,
    get_room_summary,
)

def home_view(request):
    groups = StudentGroup.objects.select_related('academic_group').all().order_by('name')
    teachers = Teacher.objects.select_related('department').all().order_by('full_name')
    rooms = Room.objects.select_related('building').all().order_by('name')

    return render(request, 'schedule/home.html', {
        'groups': groups,
        'teachers': teachers,
        'rooms': rooms,
    })


def group_schedule_view(request, group_id):
    group = get_object_or_404(StudentGroup, pk=group_id)
    schedule = get_group_schedule(group)

    return render(request, 'schedule/group_schedule.html', {
        'group': group,
        'schedule': schedule,
    })


def teacher_schedule_view(request, teacher_id):
    teacher = get_object_or_404(Teacher, pk=teacher_id)
    schedule = get_teacher_schedule(teacher)

    return render(request, 'schedule/teacher_schedule.html', {
        'teacher': teacher,
        'schedule': schedule,
    })


def room_load_view(request, room_id):
    room = get_object_or_404(Room, pk=room_id)
    schedule = get_room_load(room)

    return render(request, 'schedule/room_load.html', {
        'room': room,
        'schedule': schedule,
    })

def reports_home_view(request):
    groups = StudentGroup.objects.select_related('academic_group').all().order_by('name')
    departments = Department.objects.all().order_by('name')
    return render(request, 'schedule/reports_home.html', {
        'groups': groups,
        'departments': departments,
    })


def multi_group_chessboard_view(request):
    all_groups = StudentGroup.objects.select_related('academic_group').all().order_by('name')
    selected_ids = request.GET.getlist('group')

    selected_groups = all_groups.filter(id__in=selected_ids) if selected_ids else all_groups.none()
    groups, board = [], []

    if selected_ids:
        groups, board = get_multi_group_chessboard(selected_groups)

    return render(request, 'schedule/multi_group_chessboard.html', {
        'all_groups': all_groups,
        'selected_ids': selected_ids,
        'groups': groups,
        'board': board,
    })


def attestation_schedule_view(request):
    all_groups = StudentGroup.objects.select_related('academic_group').all().order_by('name')
    selected_ids = request.GET.getlist('group')
    kind = request.GET.get('kind', 'all')

    entries = get_attestation_schedule(
        group_ids=selected_ids if selected_ids else None,
        kind=kind,
    )

    return render(request, 'schedule/attestation_schedule.html', {
        'all_groups': all_groups,
        'selected_ids': selected_ids,
        'kind': kind,
        'entries': entries,
    })


def department_teacher_plan_view(request, department_id):
    department = get_object_or_404(Department, pk=department_id)
    rows = get_department_teacher_plan_rows(department)

    return render(request, 'schedule/department_teacher_plan.html', {
        'department': department,
        'rows': rows,
    })


def room_summary_view(request):
    by_room_type, by_building, by_time = get_room_summary()
    return render(request, 'schedule/room_summary.html', {
        'by_room_type': by_room_type,
        'by_building': by_building,
        'by_time': by_time,
    })