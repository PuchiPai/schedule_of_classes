from django.shortcuts import render, get_object_or_404

from .models import StudentGroup, Teacher, Room
from .services import get_group_schedule, get_teacher_schedule, get_room_load


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