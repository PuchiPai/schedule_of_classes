from django.db import models, transaction
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.db.models import Q
from datetime import datetime, date


def slots_overlap(slot_a, slot_b):
    """
    Проверка пересечения двух пар по времени.
    true, если интервалы пересекаются.
    """
    return slot_a.start_time < slot_b.end_time and slot_b.start_time < slot_a.end_time


# 1. Подразделения (иерархия: Университет → Школа → Кафедра)
class Department(models.Model):
    DEPT_TYPES = [
        ('university', 'Университет'),
        ('school', 'Школа / Институт'),
        ('department', 'Департамент'),
        ('chair', 'Кафедра'),
    ]
    name = models.CharField(max_length=255, verbose_name="Название подразделения")
    dept_type = models.CharField(max_length=20, choices=DEPT_TYPES, verbose_name="Тип подразделения")
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        verbose_name="Вышестоящее подразделение"
    )

    class Meta:
        verbose_name = "Подразделение"
        verbose_name_plural = "Подразделения"

    def clean(self):
        hierarchy = {
            'school': 'university',
            'department': 'school',
            'chair': 'department',
        }

        if self.dept_type == 'university':
            if self.parent is not None:
                raise ValidationError({'parent': 'У университета не должно быть вышестоящего подразделения.'})
        else:
            if not self.parent:
                raise ValidationError({'parent': 'Для этого типа подразделения нужно указать вышестоящее подразделение.'})

            expected = hierarchy.get(self.dept_type)
            if expected and self.parent.dept_type != expected:
                raise ValidationError({
                    'parent': f'Для типа "{self.get_dept_type_display()}" вышестоящее подразделение должно быть "{expected}".'
                })

    def __str__(self):
        return self.name


# 2. Преподаватели
class Teacher(models.Model):
    full_name = models.CharField(max_length=255, verbose_name="ФИО")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, verbose_name="Подразделение (Кафедра)")
    academic_degree = models.CharField(max_length=100, blank=True, verbose_name="Учёная степень")
    academic_title = models.CharField(max_length=100, blank=True, verbose_name="Учёное звание")
    position = models.CharField(max_length=100, verbose_name="Должность")
    max_hours_per_day = models.IntegerField(default=8, verbose_name="Макс. часов в день")

    class Meta:
        verbose_name = "Преподаватель"
        verbose_name_plural = "Преподаватели"

    def __str__(self):
        return self.full_name


# 3. Академическая группа (номер группы в направлении)
class AcademicGroup(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="Шифр группы")
    direction = models.CharField(max_length=200, verbose_name="Направление подготовки")

    class Meta:
        verbose_name = "Академическая группа"
        verbose_name_plural = "Академические группы"

    def __str__(self):
        return self.name


# 4. Учебная группа (подгруппа, поток, сборная)
class StudentGroup(models.Model):
    GROUP_TYPES = [
        ('full', 'Полная группа'),
        ('subgroup', 'Подгруппа'),
        ('stream', 'Поток'),
        ('mixed', 'Сборная'),
    ]
    name = models.CharField(max_length=50, unique=True, verbose_name="Название учебной группы")
    group_type = models.CharField(max_length=20, choices=GROUP_TYPES, verbose_name="Тип группы")
    academic_group = models.ForeignKey(
        AcademicGroup,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='primary_student_groups',
        verbose_name="Основная академическая группа"
    )
    student_count = models.PositiveIntegerField(verbose_name="Количество обучающихся")

    class Meta:
        verbose_name = "Учебная группа"
        verbose_name_plural = "Учебные группы"

    def __str__(self):
        return self.name

class StudentGroupAcademicGroup(models.Model):
    student_group = models.ForeignKey(
        StudentGroup,
        on_delete=models.CASCADE,
        related_name='academic_bindings',
        verbose_name="Учебная группа"
    )
    academic_group = models.ForeignKey(
        AcademicGroup,
        on_delete=models.PROTECT,
        related_name='group_bindings',
        verbose_name="Академическая группа"
    )

    class Meta:
        verbose_name = "Связь учебной группы и академической группы"
        verbose_name_plural = "Связи учебных групп и академических групп"
        constraints = [
            models.UniqueConstraint(
                fields=['student_group', 'academic_group'],
                name='unique_student_group_academic_group'
            )
        ]

    def __str__(self):
        return f"{self.student_group.name} → {self.academic_group.name}"


# 5. Корпус
class Building(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название/Номер корпуса")
    address = models.CharField(max_length=255, blank=True, verbose_name="Адрес")

    class Meta:
        verbose_name = "Корпус"
        verbose_name_plural = "Корпуса"

    def __str__(self):
        return self.name


# 5.1. Расстояния между корпусами (НОВАЯ МОДЕЛЬ)
class BuildingDistance(models.Model):
    from_building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='distances_from', verbose_name="От корпуса")
    to_building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='distances_to', verbose_name="До корпуса")
    minutes = models.PositiveIntegerField(verbose_name="Время в пути (мин)")

    class Meta:
        verbose_name = "Расстояние между корпусами"
        verbose_name_plural = "Расстояния между корпусами"
        constraints = [
            models.UniqueConstraint(fields=['from_building', 'to_building'], name='unique_building_pair')
        ]

    def clean(self):
        if self.from_building_id == self.to_building_id:
            raise ValidationError({'to_building': 'Корпус не может быть указан сам с собой.'})

        reverse_exists = BuildingDistance.objects.filter(
            from_building=self.to_building,
            to_building=self.from_building
        ).exclude(pk=self.pk).exists()

        if reverse_exists:
            raise ValidationError('Расстояние между этими корпусами уже задано в обратном направлении.')

    def __str__(self):
        return f"{self.from_building.name} ↔ {self.to_building.name}: {self.minutes} мин."


# 6. Аудитория (Оставлен только один класс, 'online' удален)
class Room(models.Model):
    ROOM_TYPES = [
        ('lecture', 'Лекционная'),
        ('practice', 'Практическая'),
        ('lab', 'Лаборатория'),
        ('computer', 'Компьютерный класс'),
        ('hall', 'Спортивный зал'),
    ]
    name = models.CharField(max_length=50, unique=True, verbose_name="Номер/Имя аудитории")
    building = models.ForeignKey(Building, on_delete=models.PROTECT, verbose_name="Корпус")
    capacity = models.PositiveIntegerField(verbose_name="Вместимость (мест)")
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES, verbose_name="Тип помещения")

    class Meta:
        verbose_name = "Аудитория"
        verbose_name_plural = "Аудитории"

    def __str__(self):
        return f"{self.building.name} - {self.name} ({self.get_room_type_display()})"


# 7. Дисциплина
class Discipline(models.Model):
    name = models.CharField(max_length=255, unique=True, verbose_name="Наименование дисциплины")

    class Meta:
        verbose_name = "Дисциплина"
        verbose_name_plural = "Дисциплины"

    def __str__(self):
        return self.name


# 8. Тип занятия (справочник)
class LessonType(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="Название типа")
    default_duration_minutes = models.IntegerField(verbose_name="Длительность (мин)")

    class Meta:
        verbose_name = "Тип занятия"
        verbose_name_plural = "Типы занятий"

    def __str__(self):
        return self.name


# 9. Учебный план (на семестр)
class Curriculum(models.Model):
    EXAM_TYPES = [
        ('exam', 'Экзамен'),
        ('credit', 'Зачёт'),
        ('none', 'Без отчетности'),
    ]

    academic_group = models.ForeignKey(AcademicGroup, on_delete=models.PROTECT, verbose_name="Академическая группа")
    discipline = models.ForeignKey(Discipline, on_delete=models.PROTECT, verbose_name="Дисциплина")
    semester = models.PositiveSmallIntegerField(
        verbose_name="Семестр",
        validators=[MinValueValidator(1), MaxValueValidator(8)]
    )
    year = models.PositiveSmallIntegerField(
        verbose_name="Курс",
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    weeks = models.PositiveSmallIntegerField(
        default=18,
        validators=[MinValueValidator(18)],
        verbose_name="Количество недель"
    )
    lecture_hours = models.PositiveIntegerField(default=0, verbose_name="Лекционные часы")
    practice_hours = models.PositiveIntegerField(default=0, verbose_name="Практические часы")
    lab_hours = models.PositiveIntegerField(default=0, verbose_name="Лабораторные часы")
    exam_type = models.CharField(max_length=10, choices=EXAM_TYPES, null=True, blank=True, verbose_name="Вид отчетности")

    class Meta:
        verbose_name = "Учебный план"
        verbose_name_plural = "Учебные планы"
        constraints = [
            models.UniqueConstraint(
                fields=['academic_group', 'discipline', 'year', 'semester'],
                name='unique_curriculum_item'
            )
        ]

    def __str__(self):
        return f"{self.discipline.name} - {self.academic_group.name} ({self.year} курс, {self.semester} семестр)"

    @property
    def total_hours(self):
        return (self.lecture_hours or 0) + (self.practice_hours or 0) + (self.lab_hours or 0)

    @property
    def hours_per_week(self):
        return round(self.total_hours / self.weeks, 2) if self.weeks else 0

    @property
    def pairs_per_week(self):
        return round((self.total_hours / 2) / self.weeks, 2) if self.weeks else 0


# 10. Учебное поручение
class TeacherAssignment(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.PROTECT, verbose_name="Преподаватель")
    discipline = models.ForeignKey(Discipline, on_delete=models.PROTECT, verbose_name="Дисциплина")
    lesson_type = models.ForeignKey(LessonType, on_delete=models.PROTECT, verbose_name="Тип занятия")
    hours_allocated = models.IntegerField(verbose_name="Выделено часов", default=0)

    class Meta:
        verbose_name = "Учебное поручение"
        verbose_name_plural = "Учебные поручения"
        constraints = [
            models.UniqueConstraint(
                fields=['teacher', 'discipline', 'lesson_type'],
                name='unique_teacher_discipline_lesson_type'
            )
        ]

    def __str__(self):
        return f"{self.teacher.full_name} - {self.discipline.name} ({self.lesson_type.name})"


# 11. Время проведения пар (справочник)
class TimeSlot(models.Model):
    pair_number = models.PositiveSmallIntegerField(
        unique=True,
        verbose_name="Номер пары",
        validators=[MinValueValidator(1), MaxValueValidator(8)]
    )
    start_time = models.TimeField(verbose_name="Начало")
    end_time = models.TimeField(verbose_name="Окончание")

    class Meta:
        ordering = ['pair_number']
        verbose_name = "Время пары"
        verbose_name_plural = "Время пар"

    def __str__(self):
        return f"{self.pair_number} пара: {self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"


# 12. Рабочие дни (производственный календарь)
class WorkingDay(models.Model):
    WEEK_PARITY = [
        ('even', 'Чётная неделя'),
        ('odd', 'Нечётная неделя'),
        ('both', 'Обе недели'),
    ]
    WEEKDAYS = [
        (1, 'Понедельник'), (2, 'Вторник'), (3, 'Среда'),
        (4, 'Четверг'), (5, 'Пятница'), (6, 'Суббота')
    ]

    semester = models.ForeignKey(
        'Semester',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='working_days',
        verbose_name="Семестр"
    )
    date = models.DateField(verbose_name="Дата")
    weekday = models.IntegerField(choices=WEEKDAYS, verbose_name="День недели")
    is_working = models.BooleanField(default=True, verbose_name="Рабочий день")
    week_parity = models.CharField(
        max_length=10,
        choices=WEEK_PARITY,
        default='both',
        verbose_name="Чётность недели"
    )

    class Meta:
        ordering = ['date']
        verbose_name = "Учебный день"
        verbose_name_plural = "Учебные дни"
        constraints = [
            models.UniqueConstraint(fields=['semester', 'date'], name='unique_semester_date')
        ]

    def clean(self):
        if Holiday.objects.filter(date=self.date).exists():
            self.is_working = False

    def save(self, *args, **kwargs):
        self.weekday = self.date.isoweekday()
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        status = "рабочий" if self.is_working else "выходной"
        return f"{self.date} ({self.get_weekday_display()}, {status})"

# 13. Главная таблица расписания
class ScheduleEntry(models.Model):
    WEEK_PARITY_CHOICES = [
        ('even', 'Чётная неделя'),
        ('odd', 'Нечётная неделя'),
        ('both', 'Обе недели'),
    ]
    LOCATION_TYPES = [
        ('room', 'Аудитория'),
        ('online', 'Онлайн'),
    ]

    semester = models.ForeignKey(
        'Semester',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='schedule_entries',
        verbose_name="Семестр"
    )
    student_group = models.ForeignKey(
        'StudentGroup', on_delete=models.CASCADE, related_name='schedule_entries'
    )
    teacher_assignment = models.ForeignKey(
        'TeacherAssignment', on_delete=models.CASCADE, related_name='schedule_entries'
    )
    location_type = models.CharField(
        max_length=10,
        choices=LOCATION_TYPES,
        default='room',
        verbose_name="Формат проведения"
    )
    room = models.ForeignKey(
        'Room', on_delete=models.PROTECT, null=True, blank=True, related_name='schedule_entries'
    )
    time_slot = models.ForeignKey(
        'TimeSlot', on_delete=models.PROTECT, related_name='schedule_entries'
    )
    working_day = models.ForeignKey(
        'WorkingDay', on_delete=models.PROTECT, related_name='schedule_entries'
    )
    week_parity = models.CharField(max_length=10, choices=WEEK_PARITY_CHOICES, default='both')
    is_cancelled = models.BooleanField(default=False)
    replacement = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replacements'
    )

    class Meta:
        verbose_name = 'Занятие в расписании'
        verbose_name_plural = 'Занятия в расписании'
        constraints = [
            models.UniqueConstraint(
                fields=['student_group', 'time_slot', 'working_day', 'week_parity'],
                name='unique_group_slot'
            ),
            models.UniqueConstraint(
                fields=['teacher_assignment', 'time_slot', 'working_day', 'week_parity'],
                name='unique_teacher_slot'
            ),
            models.UniqueConstraint(
                fields=['room', 'time_slot', 'working_day', 'week_parity'],
                condition=Q(room__isnull=False),
                name='unique_room_slot'
            ),
        ]

    def clean(self):
        errors = {}

        def parity_conflict(a, b):
            return a == 'both' or b == 'both' or a == b

        def slot_minutes(slot):
            start = datetime.combine(date.min, slot.start_time)
            end = datetime.combine(date.min, slot.end_time)
            return int((end - start).total_seconds() / 60)

        def get_travel_minutes(from_building, to_building):
            if from_building.id == to_building.id:
                return 0
            dist = BuildingDistance.objects.filter(
                from_building=from_building,
                to_building=to_building
            ).first() or BuildingDistance.objects.filter(
                from_building=to_building,
                to_building=from_building
            ).first()
            if not dist:
                raise ValidationError({
                    'room': f'Не задано расстояние между корпусами "{from_building.name}" и "{to_building.name}".'
                })
            return dist.minutes

        if self.working_day and not self.working_day.is_working:
            errors['working_day'] = 'Нельзя ставить занятие в нерабочий день.'

        if self.semester and self.working_day and self.working_day.semester_id != self.semester_id:
            errors['working_day'] = 'Дата занятия должна принадлежать выбранному семестру.'

        if self.location_type == 'room' and not self.room:
            errors['room'] = 'Для очного занятия нужно указать аудиторию.'

        if self.location_type == 'online':
            self.room = None

        if self.room and self.student_group and self.room.capacity < self.student_group.student_count:
            errors['room'] = 'В аудитории недостаточно мест для этой группы.'

        if self.room and self.teacher_assignment and self.teacher_assignment.lesson_type:
            lesson_name = self.teacher_assignment.lesson_type.name.lower()
            room_type = self.room.room_type.lower()
            if ('лаб' in lesson_name) and room_type not in ['lab', 'computer']:
                errors['room'] = 'Лабораторные занятия можно проводить только в лаборатории или компьютерном классе.'

        if self.working_day and self.time_slot and self.student_group and self.teacher_assignment:
            same_day = ScheduleEntry.objects.filter(
                semester=self.semester,
                working_day=self.working_day,
                is_cancelled=False,
            ).exclude(pk=self.pk).select_related(
                'time_slot',
                'teacher_assignment__teacher',
                'room__building'
            )

            # Конфликт по времени
            for entry in same_day:
                if not parity_conflict(entry.week_parity, self.week_parity):
                    continue
                if not slots_overlap(entry.time_slot, self.time_slot):
                    continue

                if entry.student_group_id == self.student_group_id:
                    errors['student_group'] = 'У группы есть пересечение по времени.'

                if entry.teacher_assignment.teacher_id == self.teacher_assignment.teacher_id:
                    errors['teacher_assignment'] = 'У преподавателя есть пересечение по времени.'

                if self.room_id and entry.room_id == self.room_id:
                    errors['room'] = 'Аудитория уже занята в это время.'

            # Не больше 5 пар в день для группы
            group_count = ScheduleEntry.objects.filter(
                semester=self.semester,
                student_group=self.student_group,
                working_day=self.working_day,
                week_parity=self.week_parity,
                is_cancelled=False
            ).exclude(pk=self.pk).count()
            if group_count >= 5:
                errors['student_group'] = 'Для одной учебной группы в день не должно быть больше 5 пар.'

            # Не больше 5 пар в день для преподавателя
            teacher_count = ScheduleEntry.objects.filter(
                semester=self.semester,
                teacher_assignment__teacher=self.teacher_assignment.teacher,
                working_day=self.working_day,
                week_parity=self.week_parity,
                is_cancelled=False
            ).exclude(pk=self.pk).count()
            if teacher_count >= 5:
                errors['teacher_assignment'] = 'Преподаватель не может работать больше 5 пар в день.'

            # Не больше 8 астрономических часов в день
            teacher_entries = list(ScheduleEntry.objects.filter(
                semester=self.semester,
                teacher_assignment__teacher=self.teacher_assignment.teacher,
                working_day=self.working_day,
                week_parity=self.week_parity,
                is_cancelled=False
            ).exclude(pk=self.pk).select_related('time_slot'))

            teacher_total_minutes = sum(slot_minutes(e.time_slot) for e in teacher_entries) + slot_minutes(self.time_slot)
            if teacher_total_minutes > 480:
                errors['teacher_assignment'] = 'Преподаватель не может работать больше 8 астрономических часов в день.'

            # Перерывы между занятиями не более 1,5 часа
            group_entries = list(ScheduleEntry.objects.filter(
                semester=self.semester,
                student_group=self.student_group,
                working_day=self.working_day,
                week_parity=self.week_parity,
                is_cancelled=False
            ).exclude(pk=self.pk).select_related('time_slot', 'room__building'))

            teacher_entries = list(ScheduleEntry.objects.filter(
                semester=self.semester,
                teacher_assignment__teacher=self.teacher_assignment.teacher,
                working_day=self.working_day,
                week_parity=self.week_parity,
                is_cancelled=False
            ).exclude(pk=self.pk).select_related('time_slot', 'room__building'))

            for entries in (group_entries, teacher_entries):
                entries = entries + [self]
                entries.sort(key=lambda x: x.time_slot.start_time)

                for prev, curr in zip(entries, entries[1:]):
                    gap = int((
                        datetime.combine(date.min, curr.time_slot.start_time) -
                        datetime.combine(date.min, prev.time_slot.end_time)
                    ).total_seconds() / 60)

                    if gap > 90:
                        errors['time_slot'] = 'Между учебными занятиями не должно быть перерыва более 1,5 часа.'

                    if prev.room and curr.room and prev.room_id != curr.room_id:
                        travel = get_travel_minutes(prev.room.building, curr.room.building)
                        if travel > gap:
                            errors['room'] = 'Недостаточно времени на переход между корпусами.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            return super().save(*args, **kwargs)

    def __str__(self):
        place = self.room.name if self.room else 'онлайн'
        return (
            f'{self.student_group.name} — {self.teacher_assignment.discipline.name} '
            f'({self.working_day.date}, {self.time_slot.pair_number} пара, {place})'
        )


class Semester(models.Model):
    title = models.CharField(max_length=100, verbose_name="Семестр")
    start_date = models.DateField(verbose_name="Дата начала")
    weeks = models.PositiveSmallIntegerField(default=18, verbose_name="Количество недель")

    class Meta:
        verbose_name = "Семестр"
        verbose_name_plural = "Семестры"

    def __str__(self):
        return self.title


class Holiday(models.Model):
    date = models.DateField(unique=True, verbose_name="Дата")
    name = models.CharField(max_length=255, verbose_name="Название праздника")

    class Meta:
        verbose_name = "Праздник"
        verbose_name_plural = "Праздники"

    def __str__(self):
        return f"{self.date}: {self.name}"