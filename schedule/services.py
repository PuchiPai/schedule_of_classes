from math import ceil

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q

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
    day_entries = ScheduleEntry.objects.filter(
        working_day=working_day,
        is_cancelled=False,
    ).select_related('student_group', 'teacher_assignment__teacher', 'room')

    if week_parity != 'both':
        day_entries = day_entries.filter(
            Q(week_parity='both') | Q(week_parity=week_parity)
        )

    teacher = teacher_assignment.teacher

    group_entries = day_entries.filter(student_group=student_group)
    teacher_entries = day_entries.filter(teacher_assignment__teacher=teacher)

    # лимит 5 пар в день для группы
    if group_entries.count() >= MAX_PAIRS_PER_DAY:
        return False

    # лимит 5 пар в день для преподавателя
    if teacher_entries.count() >= MAX_PAIRS_PER_DAY:
        return False

    # конфликт по времени
    if day_entries.filter(time_slot=time_slot, student_group=student_group).exists():
        return False
    if day_entries.filter(time_slot=time_slot, teacher_assignment__teacher=teacher).exists():
        return False
    if room and day_entries.filter(time_slot=time_slot, room=room).exists():
        return False

    return True


def find_free_slot(student_group, teacher_assignment, room=None, week_parity='both'):
    days = WorkingDay.objects.filter(is_working=True).order_by('date')

    if week_parity != 'both':
        days = days.filter(Q(week_parity='both') | Q(week_parity=week_parity))

    # по ТЗ больше 5 пар в день не ставим
    time_slots = TimeSlot.objects.filter(pair_number__lte=5).order_by('pair_number')

    for day in days:
        for slot in time_slots:
            if slot_is_free(day, slot, week_parity, student_group, teacher_assignment, room):
                return day, slot

    return None, None


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
    Делает демо-расписание автоматически.
    """
    if clear_existing:
        ScheduleEntry.objects.filter(
            student_group__academic_group=academic_group
        ).delete()

    curricula = Curriculum.objects.filter(
        academic_group=academic_group,
        semester=semester,
    ).select_related('discipline', 'academic_group')

    if year is not None:
        curricula = curricula.filter(year=year)

    student_group = get_main_student_group(academic_group)
    if not student_group:
        raise ValidationError(
            f'Для академической группы {academic_group.name} не найдена учебная группа.'
        )

    created_entries = []

    for curriculum in curricula:
        parts = [
            ('lecture', curriculum.lecture_hours or 0),
            ('practice', curriculum.practice_hours or 0),
            ('lab', curriculum.lab_hours or 0),
        ]
        parts = [(p, h) for p, h in parts if h > 0]

        for part, hours in parts:
            # временно ограничиваем число создаваемых записей,
            # чтобы генерация не висла на большом учебном плане
            lesson_count = min(2, ceil(hours / 2))

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
                        f"Не найден слот для {curriculum.discipline.name} ({part})"
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

    return created_entries