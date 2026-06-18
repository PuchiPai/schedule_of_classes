from django.shortcuts import render, get_object_or_404
from django.db.models import Sum
from datetime import date, timedelta

from django.contrib import messages
from django.shortcuts import redirect

from collections import defaultdict
from .models import StudentGroup, TimeSlot, Semester, ScheduleEntry, TeacherAssignment
from .services import get_active_semester


def copy_schedule_view(request):
    if request.method == 'POST':
        source_group_id = request.POST.get('source_group')
        target_group_id = request.POST.get('target_group')
        source_week_start = request.POST.get('source_week_start')
        source_week_end = request.POST.get('source_week_end')

        if not source_group_id or not target_group_id:
            messages.error(request, 'Выберите группу-источник и группу-назначение')
            return redirect('schedule:copy_schedule')

        source_group = get_object_or_404(StudentGroup, pk=source_group_id)
        target_group = get_object_or_404(StudentGroup, pk=target_group_id)

        entries = ScheduleEntry.objects.filter(
            student_group=source_group,
            is_cancelled=False,
        ).select_related('teacher_assignment', 'time_slot', 'working_day', 'room', 'semester')

        if source_week_start and source_week_end:
            entries = entries.filter(
                working_day__date__gte=source_week_start,
                working_day__date__lte=source_week_end
            )

        copied_count = 0
        for entry in entries:
            working_day, time_slot = find_free_slot(
                student_group=target_group,
                teacher_assignment=entry.teacher_assignment,
                room=entry.room,
                week_parity=entry.week_parity,
            )

            if working_day and time_slot:
                ScheduleEntry.objects.create(
                    semester=entry.semester,
                    student_group=target_group,
                    teacher_assignment=entry.teacher_assignment,
                    room=entry.room,
                    time_slot=time_slot,
                    working_day=working_day,
                    week_parity=entry.week_parity,
                    location_type=entry.location_type,
                )
                copied_count += 1

        messages.success(request, f'Скопировано {copied_count} занятий для группы {target_group.name}')
        return redirect('schedule:group_schedule', group_id=target_group_id)

    all_groups = StudentGroup.objects.select_related('academic_group').all().order_by('name')
    return render(request, 'schedule/copy_schedule.html', {'all_groups': all_groups})

from .models import StudentGroup, Department, Room, Teacher
from .services import (
    get_group_schedule,
    get_teacher_schedule,
    get_room_load,
    get_attestation_schedule,
    get_department_teacher_plan_rows,
    get_multi_group_chessboard,
    get_room_summary,
    find_free_slot,
)

def get_active_semester():
    today = date.today()
    semester = Semester.objects.filter(start_date__lte=today).order_by('-start_date').first()
    if semester:
        return semester
    return Semester.objects.order_by('-start_date').first()


def get_week_dates(semester=None, week_number=None):
    """
    Возвращает даты начала и конца недели.
    Если week_number не указан, возвращает текущую неделю семестра.
    """
    semester = semester or get_active_semester()
    if semester is None:
        raise ValueError('Не создан ни один семестр.')

    today = date.today()

    if week_number is None or week_number == 0:
        days_since_start = (today - semester.start_date).days
        week_number = max(1, min(semester.weeks, days_since_start // 7 + 1))

    week_start = semester.start_date + timedelta(weeks=week_number - 1)
    week_end = week_start + timedelta(days=5)  # Пн-Сб

    return week_number, week_start, week_end, semester.weeks

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

    week_parity = request.GET.get('week_parity', 'all')  # all / even / odd / both
    entries = get_group_schedule(group)

    if week_parity in ['even', 'odd', 'both']:
        entries = entries.filter(week_parity=week_parity)

    time_slots = list(TimeSlot.objects.all().order_by('pair_number'))
    day_numbers = [1, 2, 3, 4, 5, 6]

    cells = defaultdict(list)
    for entry in entries.select_related(
        'teacher_assignment__teacher',
        'teacher_assignment__discipline',
        'teacher_assignment__lesson_type',
        'room__building',
        'time_slot',
        'working_day'
    ):
        cells[(entry.time_slot.pair_number, entry.working_day.weekday)].append(entry)

    rows = []
    for slot in time_slots:
        row = {'slot': slot, 'cells': []}
        for day in day_numbers:
            row['cells'].append(cells.get((slot.pair_number, day), []))
        rows.append(row)

    return render(request, 'schedule/group_schedule.html', {
        'group': group,
        'rows': rows,
        'day_numbers': day_numbers,
        'week_parity': week_parity,
    })


def teacher_schedule_view(request, teacher_id):
    teacher = get_object_or_404(Teacher, pk=teacher_id)
    schedule = get_teacher_schedule(teacher)

    # Подготавливаем данные для сетки
    time_slots = TimeSlot.objects.all().order_by('pair_number')
    day_numbers = [1, 2, 3, 4, 5, 6]  # Пн-Сб

    return render(request, 'schedule/teacher_schedule.html', {
        'teacher': teacher,
        'schedule': schedule,
        'time_slots': time_slots,
        'day_numbers': day_numbers,
        'entries_by_slot': schedule,
    })


def room_load_view(request, room_id):
    room = get_object_or_404(Room, pk=room_id)
    schedule = get_room_load(room)

    # Подготавливаем данные для сетки
    time_slots = TimeSlot.objects.all().order_by('pair_number')
    day_numbers = [1, 2, 3, 4, 5, 6]  # Пн-Сб

    return render(request, 'schedule/room_load.html', {
        'room': room,
        'schedule': schedule,
        'time_slots': time_slots,
        'day_numbers': day_numbers,
        'entries_by_slot': schedule,
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

    week_param = request.GET.get('week', '0')
    current_week = int(week_param) if week_param.isdigit() else 0

    semester = get_active_semester()
    current_week, week_start, week_end, semester_weeks = get_week_dates(semester, current_week)

    if selected_ids:
        groups, board = get_multi_group_chessboard(selected_groups, week_start, week_end)

    return render(request, 'schedule/multi_group_chessboard.html', {
        'all_groups': all_groups,
        'selected_ids': selected_ids,
        'groups': groups,
        'board': board,
        'current_week': current_week,
        'week_start': week_start,
        'week_end': week_end,
        'prev_week': current_week - 1 if current_week > 1 else None,
        'next_week': current_week + 1 if current_week < semester_weeks else None,
    })


def attestation_schedule_view(request):
    all_groups = StudentGroup.objects.select_related('academic_group').all().order_by('name')
    selected_ids = request.GET.getlist('group')
    kind = request.GET.get('kind', 'all')

    # Получаем QuerySet и сразу материализуем в список
    entries_qs = get_attestation_schedule(
        group_ids=selected_ids if selected_ids else None,
        kind=kind,
    )
    entries = list(entries_qs)  # Материализуем один раз

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


def schedule_table_view(request):
    """Общее расписание в виде таблицы по дням недели с фильтрами"""
    # Получаем все справочники для фильтров
    all_groups = StudentGroup.objects.select_related('academic_group').all().order_by('name')
    all_teachers = Teacher.objects.select_related('department').all().order_by('full_name')
    all_rooms = Room.objects.select_related('building').all().order_by('name')

    # Получаем параметры фильтров из GET-запроса
    group_id = request.GET.get('group')
    teacher_id = request.GET.get('teacher')
    room_id = request.GET.get('room')
    weekday = request.GET.get('weekday')
    week_parity = request.GET.get('week_parity')

    # Базовый queryset
    entries = ScheduleEntry.objects.select_related(
        'student_group__academic_group',
        'teacher_assignment__teacher',
        'teacher_assignment__discipline',
        'teacher_assignment__lesson_type',
        'room__building',
        'time_slot',
        'working_day'
    ).filter(
        working_day__is_working=True
    )

    # Применяем фильтры
    if group_id:
        entries = entries.filter(student_group_id=group_id)
    if teacher_id:
        entries = entries.filter(teacher_assignment__teacher_id=teacher_id)
    if room_id:
        entries = entries.filter(room_id=room_id)
    if weekday:
        entries = entries.filter(working_day__weekday=weekday)
    if week_parity and week_parity != 'all':
        entries = entries.filter(week_parity=week_parity)

    # Сортируем
    entries = entries.order_by('working_day__weekday', 'time_slot__pair_number')

    # Получаем временные слоты
    time_slots = TimeSlot.objects.all().order_by('pair_number')

    # Дни недели
    weekdays = {
        1: 'Понедельник',
        2: 'Вторник',
        3: 'Среда',
        4: 'Четверг',
        5: 'Пятница',
        6: 'Суббота',
    }

    return render(request, 'schedule/schedule_table.html', {
        'time_slots': time_slots,
        'entries': entries,
        'weekdays': weekdays,
        'all_groups': all_groups,
        'all_teachers': all_teachers,
        'all_rooms': all_rooms,
        'selected_group': group_id,
        'selected_teacher': teacher_id,
        'selected_room': room_id,
        'selected_weekday': weekday,
        'selected_week_parity': week_parity,
    })


def teacher_assignment_report_view(request):
    """Отчёт по учебным поручениям преподавателей"""
    assignments = TeacherAssignment.objects.select_related(
        'teacher__department',
        'discipline',
        'lesson_type'
    ).order_by('teacher__full_name', 'discipline__name')

    # Фильтр по преподавателю (если передан)
    teacher_id = request.GET.get('teacher')
    if teacher_id:
        assignments = assignments.filter(teacher_id=teacher_id)

    # Группировка по преподавателям
    teachers = Teacher.objects.all().order_by('full_name')

    return render(request, 'schedule/teacher_assignment_report.html', {
        'assignments': assignments,
        'teachers': teachers,
        'selected_teacher': teacher_id,
    })


def teacher_workload_view(request):
    """Подсчёт нагрузки преподавателей"""
    # Получаем все поручения с часами
    assignments = TeacherAssignment.objects.select_related(
        'teacher__department',
        'lesson_type'
    ).values(
        'teacher__id',
        'teacher__full_name',
        'teacher__department__name',
        'lesson_type__name'
    ).annotate(
        total_hours=Sum('hours_allocated')
    ).order_by('teacher__full_name')

    # Агрегируем по преподавателям
    workload = {}
    for item in assignments:
        teacher_id = item['teacher__id']
        if teacher_id not in workload:
            workload[teacher_id] = {
                'full_name': item['teacher__full_name'],
                'department': item['teacher__department__name'],
                'lectures': 0,
                'practices': 0,
                'labs': 0,
                'total': 0,
            }

        lesson_type = item['lesson_type__name'].lower()
        hours = item['total_hours'] or 0

        if 'лекц' in lesson_type:
            workload[teacher_id]['lectures'] += hours
        elif 'практ' in lesson_type or 'семин' in lesson_type:
            workload[teacher_id]['practices'] += hours
        elif 'лаб' in lesson_type:
            workload[teacher_id]['labs'] += hours

        workload[teacher_id]['total'] += hours

    return render(request, 'schedule/teacher_workload.html', {
        'workload': workload.values(),
    })