from collections import defaultdict
from math import ceil

from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from django.db.models import Q, Count

from .models import (
    ScheduleEntry,
    StudentGroup,
    TeacherAssignment,
    WorkingDay,
    TimeSlot,
    Curriculum,
    LessonType,
    Room,
    AcademicGroup,
    Teacher

)

import logging
logger = logging.getLogger(__name__)


@transaction.atomic
def create_schedule_entry(
    student_group,
    teacher_assignment,
    time_slot,
    working_day,
    week_parity='both',
    room=None,
    is_cancelled=False,
    replacement=None,
):
    entry = ScheduleEntry(
        student_group=student_group,
        teacher_assignment=teacher_assignment,
        time_slot=time_slot,
        working_day=working_day,
        week_parity=week_parity,
        room=room,
        is_cancelled=is_cancelled,
        replacement=replacement,
    )
    entry.full_clean()
    entry.save()
    return entry


def cancel_schedule_entry(entry_id):
    entry = ScheduleEntry.objects.get(pk=entry_id)
    entry.is_cancelled = True
    entry.save(update_fields=['is_cancelled'])
    return entry


@transaction.atomic
def copy_schedule_for_day(source_day, target_day, week_parity=None):
    """
    Копирует занятия с одного дня на другой.
    Используется для переноса/дублирования расписания.
    """
    qs = ScheduleEntry.objects.filter(working_day=source_day, is_cancelled=False)

    if week_parity:
        qs = qs.filter(week_parity=week_parity)

    copied = []
    for item in qs:
        new_item = ScheduleEntry(
            student_group=item.student_group,
            teacher_assignment=item.teacher_assignment,
            room=item.room,
            time_slot=item.time_slot,
            working_day=target_day,
            week_parity=item.week_parity,
            replacement=item,
            is_cancelled=False,
        )
        new_item.full_clean()
        new_item.save()
        copied.append(new_item)

    return copied


def get_group_schedule(student_group):
    return (
        ScheduleEntry.objects
        .filter(student_group=student_group, is_cancelled=False)
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room',
            'time_slot',
            'working_day',
        )
        .order_by('working_day__date', 'time_slot__pair_number')
    )


def get_teacher_schedule(teacher):
    return (
        ScheduleEntry.objects
        .filter(teacher_assignment__teacher=teacher, is_cancelled=False)
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room',
            'time_slot',
            'working_day',
        )
        .order_by('working_day__date', 'time_slot__pair_number')
    )


def get_room_load(room):
    return (
        ScheduleEntry.objects
        .filter(room=room, is_cancelled=False)
        .select_related('time_slot', 'working_day', 'student_group')
        .order_by('working_day__date', 'time_slot__pair_number')
    )

def get_main_student_group(academic_group):
    """
    Берём основную учебную группу для академической группы.
    Сначала пробуем полную группу, если её нет — любую первую.
    """
    group = (
        StudentGroup.objects
        .filter(academic_group=academic_group, group_type='full')
        .order_by('name')
        .first()
    )
    if group:
        return group

    return (
        StudentGroup.objects
        .filter(academic_group=academic_group)
        .order_by('name')
        .first()
    )


def get_lesson_type_for_part(part: str) -> LessonType:
    """
    part: lecture | practice | lab
    """
    aliases = {
        'lecture': ['лекция'],
        'practice': ['практика', 'семинар'],
        'lab': ['лабораторная работа', 'лабораторная', 'лаб'],
    }

    names = aliases.get(part, [])
    for name in names:
        lesson_type = LessonType.objects.filter(name__icontains=name).first()
        if lesson_type:
            return lesson_type

    raise ValidationError(f'Не найден тип занятия для части: {part}')


def get_room_for_part(part: str, students_count: int):
    """
    Подбирает аудиторию под тип занятия и вместимость.
    """
    room_types = {
        'lecture': ['lecture', 'hall'],
        'practice': ['practice', 'lecture', 'hall'],
        'lab': ['lab', 'computer'],
    }

    allowed_types = room_types.get(part, [])
    room = (
        Room.objects
        .filter(room_type__in=allowed_types, capacity__gte=students_count)
        .order_by('capacity')
        .first()
    )
    return room

MAX_PAIRS_PER_DAY = 5

def slot_is_free(
    working_day,
    time_slot,
    week_parity,
    student_group,
    teacher_assignment,
    room=None
):
    base_qs = ScheduleEntry.objects.filter(
        working_day=working_day,
        is_cancelled=False,
    ).select_related('teacher_assignment__teacher')

    teacher = teacher_assignment.teacher

    if week_parity != 'both':
        parity_qs = base_qs.filter(
            Q(week_parity='both') | Q(week_parity=week_parity)
        )
    else:
        parity_qs = base_qs

    group_count = parity_qs.filter(student_group=student_group).count()
    teacher_count = parity_qs.filter(teacher_assignment__teacher=teacher).count()

    if parity_qs.filter(time_slot=time_slot, student_group=student_group).exists():
        return False

    if parity_qs.filter(time_slot=time_slot, teacher_assignment__teacher=teacher).exists():
        return False

    if room and parity_qs.filter(time_slot=time_slot, room=room).exists():
        return False

    if group_count >= MAX_PAIRS_PER_DAY:
        return False

    if teacher_count >= MAX_PAIRS_PER_DAY:
        return False

    return True

def find_free_slot(student_group, teacher_assignment, room=None, week_parity='both'):
    """
    Ищет первый свободный слот.
    Перебирает все рабочие дни и все пары из справочника.
    """
    days = WorkingDay.objects.filter(is_working=True).order_by('date')

    if week_parity != 'both':
        days = days.filter(Q(week_parity='both') | Q(week_parity=week_parity))

    time_slots = TimeSlot.objects.filter(pair_number__lte=5).order_by('pair_number')

    for day in days:
        for slot in time_slots:
            if slot_is_free(
                    working_day=day,
                    time_slot=slot,
                    week_parity=week_parity,
                    student_group=student_group,
                    teacher_assignment=teacher_assignment,
                    room=room,
            ):
                return day, slot

    return None, None

def add_attestation_sessions(curriculum, student_group, week_parity='both'):
    """
    Добавляет консультацию и итоговую аттестацию
    (зачёт или экзамен) по дисциплине.
    """
    created = []

    consultation_type = LessonType.objects.filter(name__icontains='консульта').first()
    if consultation_type:
        consultation_assignment = (
            TeacherAssignment.objects
            .filter(
                discipline=curriculum.discipline,
                lesson_type=consultation_type,
            )
            .select_related('teacher', 'discipline', 'lesson_type')
            .first()
        )

        if consultation_assignment:
            consultation_room = get_room_for_part('lecture', student_group.student_count)
            day, slot = find_free_slot(
                student_group=student_group,
                teacher_assignment=consultation_assignment,
                room=consultation_room,
                week_parity=week_parity,
            )

            if day and slot:
                exists = ScheduleEntry.objects.filter(
                    student_group=student_group,
                    teacher_assignment__discipline=curriculum.discipline,
                    teacher_assignment__lesson_type=consultation_type,
                    is_cancelled=False,
                ).exists()

                if not exists:
                    entry = ScheduleEntry(
                        student_group=student_group,
                        teacher_assignment=consultation_assignment,
                        room=consultation_room,
                        time_slot=slot,
                        working_day=day,
                        week_parity=week_parity,
                        is_cancelled=False,
                    )
                    entry.full_clean()
                    entry.save()
                    created.append(entry)

    final_type_name = None
    if curriculum.exam_type == 'exam':
        final_type_name = 'экзам'
    elif curriculum.exam_type == 'credit':
        final_type_name = 'зач'

    if final_type_name:
        final_type = LessonType.objects.filter(name__icontains=final_type_name).first()
        if final_type:
            final_assignment = (
                TeacherAssignment.objects
                .filter(
                    discipline=curriculum.discipline,
                    lesson_type=final_type,
                )
                .select_related('teacher', 'discipline', 'lesson_type')
                .first()
            )

            if final_assignment:
                final_room = get_room_for_part('lecture', student_group.student_count)
                day, slot = find_free_slot(
                    student_group=student_group,
                    teacher_assignment=final_assignment,
                    room=final_room,
                    week_parity=week_parity,
                )

                if day and slot:
                    exists = ScheduleEntry.objects.filter(
                        student_group=student_group,
                        teacher_assignment__discipline=curriculum.discipline,
                        teacher_assignment__lesson_type=final_type,
                        is_cancelled=False,
                    ).exists()

                    if not exists:
                        entry = ScheduleEntry(
                            student_group=student_group,
                            teacher_assignment=final_assignment,
                            room=final_room,
                            time_slot=slot,
                            working_day=day,
                            week_parity=week_parity,
                            is_cancelled=False,
                        )
                        entry.full_clean()
                        entry.save()
                        created.append(entry)

    return created

@transaction.atomic
def generate_demo_schedule_from_curriculum(
    academic_group: AcademicGroup,
    semester: int,
    year: int | None = None,
    week_parity: str = 'both',
    clear_existing: bool = False,
):
    """
    Генератор расписания по учебному плану.
    Заполняет семестр автоматически.
    """
    if clear_existing:
        ScheduleEntry.objects.filter(
            student_group__academic_group=academic_group
        ).delete()

    curricula = (
        Curriculum.objects
        .filter(
            academic_group=academic_group,
            semester=semester,
        )
        .select_related('discipline', 'academic_group')
    )

    if year is not None:
        curricula = curricula.filter(year=year)

    student_group = get_main_student_group(academic_group)
    if not student_group:
        raise ValidationError(
            f'Для академической группы {academic_group.name} не найдена учебная группа.'
        )

    created_entries = []

    curricula_list = list(curricula)
    curricula_list.sort(
        key=lambda c: (
                (c.lab_hours or 0) * 3 +
                (c.practice_hours or 0) * 2 +
                (c.lecture_hours or 0)
        ),
        reverse=True
    )

    for curriculum in curricula_list:
        parts = [
            ('lab', curriculum.lab_hours or 0),
            ('practice', curriculum.practice_hours or 0),
            ('lecture', curriculum.lecture_hours or 0),
        ]
        parts = [(p, h) for p, h in parts if h > 0]

        for part, hours in parts:
            lesson_count = ceil(hours / 2)

            lesson_type = get_lesson_type_for_part(part)

            assignment = (
                TeacherAssignment.objects
                .filter(
                    discipline=curriculum.discipline,
                    lesson_type=lesson_type,
                )
                .select_related('teacher', 'discipline', 'lesson_type')
                .order_by('teacher__full_name')
                .first()
            )

            if not assignment:
                logger.warning(
                    f"No teacher assignment for {curriculum.discipline.name} {part}"
                )
                continue

            room = get_room_for_part(part, student_group.student_count)

            if part == 'lab' and room is None:
                logger.warning(f"No room for lab {curriculum.discipline.name}")
                continue

            for _ in range(lesson_count):
                working_day, time_slot = find_free_slot(
                    student_group=student_group,
                    teacher_assignment=assignment,
                    room=room,
                    week_parity=week_parity,
                )

                if not working_day or not time_slot:
                    logger.warning(
                        f"Нет свободных слотов для {curriculum.discipline.name} ({part})"
                    )
                    break

                entry = ScheduleEntry(
                    student_group=student_group,
                    teacher_assignment=assignment,
                    room=room,
                    time_slot=time_slot,
                    working_day=working_day,
                    week_parity=week_parity,
                    is_cancelled=False,
                )

                try:
                    entry.full_clean()
                    entry.save()
                    created_entries.append(entry)
                except ValidationError as exc:
                    logger.warning(f"Не удалось создать занятие: {exc}")
                    continue
                except IntegrityError as exc:
                    logger.warning(f"DB conflict while creating schedule entry: {exc}")
                    continue

        created_entries.extend(
            add_attestation_sessions(
                curriculum=curriculum,
                student_group=student_group,
                week_parity=week_parity,
            )
        )

    return created_entries

@transaction.atomic
def move_schedule_entry(entry, new_day, new_slot, new_room=None):
    """
    Перенос занятия.
    Сначала создаём новое занятие, потом отменяем старое.
    Так безопаснее: если валидация не пройдёт, старое занятие не сломается.
    """
    new_entry = ScheduleEntry(
        student_group=entry.student_group,
        teacher_assignment=entry.teacher_assignment,
        room=new_room or entry.room,
        time_slot=new_slot,
        working_day=new_day,
        week_parity=entry.week_parity,
        replacement=entry,
        is_cancelled=False,
    )
    new_entry.full_clean()
    new_entry.save()

    entry.is_cancelled = True
    entry.save(update_fields=['is_cancelled'])

    return new_entry

def get_attestation_schedule(group_ids=None, kind='all'):
    qs = (
        ScheduleEntry.objects
        .filter(is_cancelled=False)
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room',
            'time_slot',
            'working_day',
        )
    )

    if group_ids:
        qs = qs.filter(student_group_id__in=group_ids)

    if kind == 'exam':
        qs = qs.filter(teacher_assignment__lesson_type__name__icontains='экзам')
    elif kind == 'credit':
        qs = qs.filter(teacher_assignment__lesson_type__name__icontains='зач')
    elif kind == 'consultation':
        qs = qs.filter(teacher_assignment__lesson_type__name__icontains='консульта')

    return qs.order_by('working_day__date', 'time_slot__pair_number')

@transaction.atomic
def create_consultation(student_group, teacher_assignment, room, day, slot):
    entry = ScheduleEntry(
        student_group=student_group,
        teacher_assignment=teacher_assignment,
        room=room,
        working_day=day,
        time_slot=slot,
        week_parity='both',
        is_cancelled=False,
    )
    entry.full_clean()
    entry.save()
    return entry

def get_department_teacher_plan(department):
    teachers = (
        Teacher.objects
        .filter(department=department)
        .select_related('department')
        .order_by('full_name')
    )

    entries = (
        ScheduleEntry.objects
        .filter(teacher_assignment__teacher__department=department, is_cancelled=False)
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room',
            'time_slot',
            'working_day',
        )
        .order_by('teacher_assignment__teacher__full_name', 'working_day__date', 'time_slot__pair_number')
    )

    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry.teacher_assignment.teacher_id].append(entry)

    return teachers, grouped


def get_multi_group_chessboard(groups, start_date=None, end_date=None):
    groups = list(groups.select_related('academic_group').order_by('name'))

    entries = (
        ScheduleEntry.objects
        .filter(student_group__in=groups, is_cancelled=False)
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room',
            'time_slot',
            'working_day',
        )
    )

    # Фильтр по диапазону дат (для одной недели)
    if start_date and end_date:
        entries = entries.filter(working_day__date__gte=start_date, working_day__date__lte=end_date)

    entries = entries.order_by('working_day__date', 'time_slot__pair_number')

    entry_map = defaultdict(list)
    for entry in entries:
        entry_map[(entry.working_day_id, entry.time_slot_id)].append(entry)

    days = (
        WorkingDay.objects
        .filter(is_working=True)
    )
    if start_date and end_date:
        days = days.filter(date__gte=start_date, date__lte=end_date)
    days = days.order_by('date')

    slots = TimeSlot.objects.filter(pair_number__lte=5).order_by('pair_number')

    board = []
    for day in days:
        rows = []
        for slot in slots:
            cell_map = {group.id: None for group in groups}
            for entry in entry_map.get((day.id, slot.id), []):
                cell_map[entry.student_group_id] = entry

            rows.append({
                'time_slot': slot,
                'cells': [cell_map[group.id] for group in groups],
            })

        board.append({
            'working_day': day,
            'rows': rows,
        })

    return groups, board

def get_room_summary():
    qs = (
        ScheduleEntry.objects
        .filter(room__isnull=False, is_cancelled=False)
        .select_related('room', 'room__building', 'time_slot')
    )

    by_room_type = list(
        qs.values('room__room_type')
        .annotate(total=Count('id'))
        .order_by('room__room_type')
    )

    by_building = list(
        qs.values('room__building__name')
        .annotate(total=Count('id'))
        .order_by('room__building__name')
    )

    by_time = list(
        qs.values('time_slot__pair_number')
        .annotate(total=Count('id'))
        .order_by('time_slot__pair_number')
    )

    return by_room_type, by_building, by_time

def get_department_teacher_plan_rows(department):
    teachers = (
        Teacher.objects
        .filter(department=department)
        .select_related('department')
        .order_by('full_name')
    )

    entries = (
        ScheduleEntry.objects
        .filter(teacher_assignment__teacher__department=department, is_cancelled=False)
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room',
            'time_slot',
            'working_day',
        )
        .order_by('teacher_assignment__teacher__full_name', 'working_day__date', 'time_slot__pair_number')
    )

    result = []
    for teacher in teachers:
        teacher_entries = [e for e in entries if e.teacher_assignment.teacher_id == teacher.id]
        result.append({
            'teacher': teacher,
            'entries': teacher_entries,
        })

    return result