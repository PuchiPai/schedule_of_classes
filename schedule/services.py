from collections import defaultdict
from math import ceil
from datetime import date, datetime

from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from django.db.models import Q, Count, Sum

from .models import (
    Semester,
    ScheduleEntry,
    StudentGroup,
    TeacherAssignment,
    WorkingDay,
    TimeSlot,
    Curriculum,
    LessonType,
    Room,
    AcademicGroup,
    Teacher,
    BuildingDistance,
)

import logging

logger = logging.getLogger(__name__)

MAX_PAIRS_PER_DAY = 5


def get_active_semester():
    """
    Возвращает активный семестр.
    Если есть семестр, который уже начался, берём последний по start_date.
    Иначе — самый поздний из созданных.
    """
    today = date.today()
    semester = Semester.objects.filter(start_date__lte=today).order_by('-start_date').first()
    if semester:
        return semester
    return Semester.objects.order_by('-start_date').first()


def _slot_minutes(slot: TimeSlot) -> int:
    start = datetime.combine(date.min, slot.start_time)
    end = datetime.combine(date.min, slot.end_time)
    return int((end - start).total_seconds() / 60)


def _travel_minutes(from_building, to_building) -> int:
    if from_building.id == to_building.id:
        return 0

    dist = BuildingDistance.objects.filter(
        from_building=from_building,
        to_building=to_building
    ).first()

    if not dist:
        dist = BuildingDistance.objects.filter(
            from_building=to_building,
            to_building=from_building
        ).first()

    if not dist:
        raise ValidationError(
            {'room': f'Не задано расстояние между корпусами "{from_building.name}" и "{to_building.name}".'}
        )

    return dist.minutes


def _parity_matches(existing_parity: str, new_parity: str) -> bool:
    return existing_parity == 'both' or new_parity == 'both' or existing_parity == new_parity


def _sequence_is_valid(entries, candidate) -> bool:
    """
    Проверяет:
    - нет ли перерыва больше 90 минут;
    - хватает ли времени на переход между корпусами.
    """
    ordered = list(entries) + [candidate]
    ordered.sort(key=lambda x: x.time_slot.start_time)

    for prev, curr in zip(ordered, ordered[1:]):
        gap = int((
            datetime.combine(date.min, curr.time_slot.start_time) -
            datetime.combine(date.min, prev.time_slot.end_time)
        ).total_seconds() / 60)

        if gap > 90:
            return False

        if prev.room and curr.room and prev.room_id != curr.room_id:
            travel = _travel_minutes(prev.room.building, curr.room.building)
            if travel > gap:
                return False

    return True


@transaction.atomic
def create_schedule_entry(
    student_group,
    teacher_assignment,
    time_slot,
    working_day,
    semester=None,
    week_parity='both',
    room=None,
    location_type='room',
    is_cancelled=False,
    replacement=None,
):
    semester = semester or get_active_semester()
    if semester is None:
        raise ValidationError('Не создан ни один семестр.')

    if location_type == 'online':
        room = None

    entry = ScheduleEntry(
        semester=semester,
        student_group=student_group,
        teacher_assignment=teacher_assignment,
        time_slot=time_slot,
        working_day=working_day,
        week_parity=week_parity,
        room=room,
        location_type=location_type,
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
def copy_schedule_for_day(source_day, target_day, semester=None, week_parity=None):
    """
    Копирует занятия с одного дня на другой.
    """
    semester = semester or get_active_semester()
    if semester is None:
        raise ValidationError('Не создан ни один семестр.')

    qs = ScheduleEntry.objects.filter(
        semester=semester,
        working_day=source_day,
        is_cancelled=False
    )

    if week_parity:
        qs = qs.filter(week_parity=week_parity)

    copied = []
    for item in qs.select_related('teacher_assignment', 'time_slot', 'room'):
        new_item = ScheduleEntry(
            semester=semester,
            student_group=item.student_group,
            teacher_assignment=item.teacher_assignment,
            room=item.room,
            location_type=item.location_type,
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


def get_group_schedule(student_group, semester=None):
    semester = semester or get_active_semester()
    qs = ScheduleEntry.objects.filter(
        semester=semester,
        student_group=student_group,
        is_cancelled=False
    )

    return (
        qs.select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room__building',
            'time_slot',
            'working_day',
        )
        .order_by('working_day__date', 'time_slot__pair_number')
    )


def get_teacher_schedule(teacher, semester=None):
    semester = semester or get_active_semester()
    qs = ScheduleEntry.objects.filter(
        semester=semester,
        teacher_assignment__teacher=teacher,
        is_cancelled=False
    )

    return (
        qs.select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room__building',
            'time_slot',
            'working_day',
        )
        .order_by('working_day__date', 'time_slot__pair_number')
    )


def get_room_load(room, semester=None):
    semester = semester or get_active_semester()
    qs = ScheduleEntry.objects.filter(
        semester=semester,
        room=room,
        is_cancelled=False
    )

    return (
        qs.select_related('time_slot', 'working_day', 'student_group', 'teacher_assignment__discipline')
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
    Если аудитория не найдена, для лекции/практики можно уйти в online.
    Лабораторные без аудитории не ставим.
    """
    room_types = {
        'lecture': ['lecture', 'hall'],
        'practice': ['practice', 'lecture', 'hall'],
        'lab': ['lab', 'computer'],
    }

    allowed_types = room_types.get(part, [])
    return (
        Room.objects
        .filter(room_type__in=allowed_types, capacity__gte=students_count)
        .order_by('capacity')
        .first()
    )


def slot_is_free(
    semester,
    working_day,
    time_slot,
    week_parity,
    student_group,
    teacher_assignment,
    room=None,
    location_type='room',
):
    """
    Проверяет, можно ли поставить занятие в данный слот.
    Учитывает:
    - пересечения,
    - максимум 5 пар в день,
    - переходы между корпусами,
    - перерывы не более 1,5 часа.
    """
    semester = semester or get_active_semester()
    if semester is None:
        return False

    base_qs = ScheduleEntry.objects.filter(
        semester=semester,
        working_day=working_day,
        is_cancelled=False,
    ).select_related(
        'teacher_assignment__teacher',
        'room__building',
        'time_slot',
    )

    teacher = teacher_assignment.teacher

    if week_parity != 'both':
        parity_qs = base_qs.filter(Q(week_parity='both') | Q(week_parity=week_parity))
    else:
        parity_qs = base_qs

    # Прямые пересечения
    if parity_qs.filter(time_slot=time_slot, student_group=student_group).exists():
        return False

    if parity_qs.filter(time_slot=time_slot, teacher_assignment__teacher=teacher).exists():
        return False

    if room and location_type == 'room' and parity_qs.filter(time_slot=time_slot, room=room).exists():
        return False

    # Лимит 5 пар в день
    group_count = parity_qs.filter(student_group=student_group).count()
    teacher_count = parity_qs.filter(teacher_assignment__teacher=teacher).count()

    if group_count >= MAX_PAIRS_PER_DAY:
        return False

    if teacher_count >= MAX_PAIRS_PER_DAY:
        return False

    # Проверка разрывов и переходов для группы
    group_entries = list(
        parity_qs.filter(student_group=student_group)
        .exclude(time_slot=time_slot)
        .select_related('room__building', 'time_slot')
    )
    candidate_group = ScheduleEntry(
        semester=semester,
        student_group=student_group,
        teacher_assignment=teacher_assignment,
        room=room,
        location_type=location_type,
        time_slot=time_slot,
        working_day=working_day,
        week_parity=week_parity,
    )
    if not _sequence_is_valid(group_entries, candidate_group):
        return False

    # Проверка разрывов и переходов для преподавателя
    teacher_entries = list(
        parity_qs.filter(teacher_assignment__teacher=teacher)
        .exclude(time_slot=time_slot)
        .select_related('room__building', 'time_slot')
    )
    candidate_teacher = ScheduleEntry(
        semester=semester,
        student_group=student_group,
        teacher_assignment=teacher_assignment,
        room=room,
        location_type=location_type,
        time_slot=time_slot,
        working_day=working_day,
        week_parity=week_parity,
    )
    if not _sequence_is_valid(teacher_entries, candidate_teacher):
        return False

    return True


def find_free_slot(semester=None, student_group=None, teacher_assignment=None, room=None, week_parity='both', location_type='room'):
    """
    Ищет первый свободный слот.
    Перебирает все рабочие дни семестра и все пары из справочника.
    """
    semester = semester or get_active_semester()
    if semester is None:
        return None, None

    days = WorkingDay.objects.filter(
        semester=semester,
        is_working=True
    ).order_by('date')

    if week_parity != 'both':
        days = days.filter(Q(week_parity='both') | Q(week_parity=week_parity))

    # По ТЗ справочник пар — 1..8
    time_slots = TimeSlot.objects.all().order_by('pair_number')

    for day in days:
        for slot in time_slots:
            if slot_is_free(
                semester=semester,
                working_day=day,
                time_slot=slot,
                week_parity=week_parity,
                student_group=student_group,
                teacher_assignment=teacher_assignment,
                room=room,
                location_type=location_type,
            ):
                return day, slot

    return None, None


def add_attestation_sessions(curriculum, student_group, semester=None, week_parity='both'):
    """
    Добавляет консультацию и итоговую аттестацию
    (зачёт или экзамен) по дисциплине.
    """
    semester = semester or get_active_semester()
    if semester is None:
        raise ValidationError('Не создан ни один семестр.')

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
            location_type = 'room' if consultation_room else 'online'

            day, slot = find_free_slot(
                semester=semester,
                student_group=student_group,
                teacher_assignment=consultation_assignment,
                room=consultation_room,
                week_parity=week_parity,
                location_type=location_type,
            )

            if day and slot:
                exists = ScheduleEntry.objects.filter(
                    semester=semester,
                    student_group=student_group,
                    teacher_assignment__discipline=curriculum.discipline,
                    teacher_assignment__lesson_type=consultation_type,
                    is_cancelled=False,
                ).exists()

                if not exists:
                    entry = ScheduleEntry(
                        semester=semester,
                        student_group=student_group,
                        teacher_assignment=consultation_assignment,
                        room=consultation_room,
                        location_type=location_type,
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
                location_type = 'room' if final_room else 'online'

                day, slot = find_free_slot(
                    semester=semester,
                    student_group=student_group,
                    teacher_assignment=final_assignment,
                    room=final_room,
                    week_parity=week_parity,
                    location_type=location_type,
                )

                if day and slot:
                    exists = ScheduleEntry.objects.filter(
                        semester=semester,
                        student_group=student_group,
                        teacher_assignment__discipline=curriculum.discipline,
                        teacher_assignment__lesson_type=final_type,
                        is_cancelled=False,
                    ).exists()

                    if not exists:
                        entry = ScheduleEntry(
                            semester=semester,
                            student_group=student_group,
                            teacher_assignment=final_assignment,
                            room=final_room,
                            location_type=location_type,
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
    schedule_semester=None,
):
    """
    Генератор расписания по учебному плану.
    semester — номер семестра в учебном плане (поле Curriculum.semester).
    schedule_semester — объект Semester, в который реально ставим занятия.
    """
    schedule_semester = schedule_semester or get_active_semester()
    if schedule_semester is None:
        raise ValidationError('Не создан ни один семестр.')

    if clear_existing:
        ScheduleEntry.objects.filter(
            semester=schedule_semester,
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

            location_type = 'room' if room else 'online'

            for _ in range(lesson_count):
                working_day, time_slot = find_free_slot(
                    semester=schedule_semester,
                    student_group=student_group,
                    teacher_assignment=assignment,
                    room=room,
                    week_parity=week_parity,
                    location_type=location_type,
                )

                if not working_day or not time_slot:
                    logger.warning(
                        f"Нет свободных слотов для {curriculum.discipline.name} ({part})"
                    )
                    break

                entry = ScheduleEntry(
                    semester=schedule_semester,
                    student_group=student_group,
                    teacher_assignment=assignment,
                    room=room,
                    location_type=location_type,
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
                semester=schedule_semester,
                week_parity=week_parity,
            )
        )

    return created_entries


@transaction.atomic
def move_schedule_entry(entry, new_day, new_slot, new_room=None, new_location_type=None, semester=None):
    """
    Перенос занятия.
    Сначала создаём новое занятие, потом отменяем старое.
    """
    semester = semester or entry.semester or get_active_semester()
    if semester is None:
        raise ValidationError('Не создан ни один семестр.')

    location_type = new_location_type or entry.location_type
    room = None if location_type == 'online' else (new_room or entry.room)

    new_entry = ScheduleEntry(
        semester=semester,
        student_group=entry.student_group,
        teacher_assignment=entry.teacher_assignment,
        room=room,
        location_type=location_type,
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


def get_attestation_schedule(group_ids=None, kind='all', semester=None):
    semester = semester or get_active_semester()
    if semester is None:
        return ScheduleEntry.objects.none()

    qs = (
        ScheduleEntry.objects
        .filter(semester=semester, is_cancelled=False)
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room__building',
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
def create_consultation(student_group, teacher_assignment, room, day, slot, semester=None):
    semester = semester or get_active_semester()
    if semester is None:
        raise ValidationError('Не создан ни один семестр.')

    location_type = 'room' if room else 'online'

    entry = ScheduleEntry(
        semester=semester,
        student_group=student_group,
        teacher_assignment=teacher_assignment,
        room=room,
        location_type=location_type,
        working_day=day,
        time_slot=slot,
        week_parity='both',
        is_cancelled=False,
    )
    entry.full_clean()
    entry.save()
    return entry


def get_department_teacher_plan(department, semester=None):
    semester = semester or get_active_semester()
    if semester is None:
        return Teacher.objects.none(), defaultdict(list)

    teachers = (
        Teacher.objects
        .filter(department=department)
        .select_related('department')
        .order_by('full_name')
    )

    entries = (
        ScheduleEntry.objects
        .filter(
            semester=semester,
            teacher_assignment__teacher__department=department,
            is_cancelled=False
        )
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room__building',
            'time_slot',
            'working_day',
        )
        .order_by('teacher_assignment__teacher__full_name', 'working_day__date', 'time_slot__pair_number')
    )

    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry.teacher_assignment.teacher_id].append(entry)

    return teachers, grouped


def get_multi_group_chessboard(groups, start_date=None, end_date=None, semester=None):
    semester = semester or get_active_semester()
    if semester is None:
        return [], []

    groups = list(groups.select_related('academic_group').order_by('name'))

    entries = (
        ScheduleEntry.objects
        .filter(
            semester=semester,
            student_group__in=groups,
            is_cancelled=False
        )
        .select_related(
            'student_group',
            'teacher_assignment__teacher',
            'teacher_assignment__discipline',
            'teacher_assignment__lesson_type',
            'room__building',
            'time_slot',
            'working_day',
        )
    )

    if start_date and end_date:
        entries = entries.filter(
            working_day__date__gte=start_date,
            working_day__date__lte=end_date
        )

    entries = entries.order_by('working_day__date', 'time_slot__pair_number')

    entry_map = defaultdict(list)
    for entry in entries:
        entry_map[(entry.working_day_id, entry.time_slot_id)].append(entry)

    days = WorkingDay.objects.filter(
        semester=semester,
        is_working=True
    )
    if start_date and end_date:
        days = days.filter(date__gte=start_date, date__lte=end_date)
    days = days.order_by('date')

    slots = TimeSlot.objects.order_by('pair_number')

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


def get_room_summary(semester=None):
    semester = semester or get_active_semester()
    if semester is None:
        return [], [], []

    qs = (
        ScheduleEntry.objects
        .filter(semester=semester, room__isnull=False, is_cancelled=False)
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


def get_department_teacher_plan_rows(department, semester=None):
    teachers, grouped = get_department_teacher_plan(department, semester=semester)

    result = []
    for teacher in teachers:
        result.append({
            'teacher': teacher,
            'entries': grouped.get(teacher.id, []),
        })

    return result


def get_group_workload_summary(student_group_id, semester_id):
    """
    Возвращает словарь с суммарной нагрузкой по типам занятий
    для конкретной группы и семестра.
    """
    result = ScheduleEntry.objects.filter(
        student_group_id=student_group_id,
        semester_id=semester_id
    ).values(
        'lesson_type__name'
    ).annotate(
        total_hours=Sum('lesson_type__duration_minutes') / 60.0,  # переводим минуты в часы
        total_lessons=Count('id')
    ).order_by('lesson_type__name')

    # Преобразуем в список словарей для удобства в шаблоне
    return list(result)