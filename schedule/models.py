from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.db.models import Q
from datetime import datetime


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
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children', verbose_name="Вышестоящее подразделение")

    class Meta:
        verbose_name = "Подразделение"
        verbose_name_plural = "Подразделения"

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
    academic_group = models.ForeignKey(AcademicGroup, on_delete=models.CASCADE, null=True, blank=True,
                                       verbose_name="Академическая группа")
    student_count = models.PositiveIntegerField(verbose_name="Количество обучающихся")

    class Meta:
        verbose_name = "Учебная группа"
        verbose_name_plural = "Учебные группы"

    def __str__(self):
        return self.name


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
    from_building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='distances_from',
                                      verbose_name="От корпуса")
    to_building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='distances_to',
                                    verbose_name="До корпуса")
    minutes = models.PositiveIntegerField(verbose_name="Время в пути (мин)")

    class Meta:
        verbose_name = "Расстояние между корпусами"
        verbose_name_plural = "Расстояния между корпусами"
        constraints = [
            models.UniqueConstraint(fields=['from_building', 'to_building'], name='unique_building_pair')
        ]

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

    academic_group = models.ForeignKey(
        AcademicGroup,
        on_delete=models.PROTECT,
        verbose_name="Академическая группа"
    )
    discipline = models.ForeignKey(
        Discipline,
        on_delete=models.PROTECT,
        verbose_name="Дисциплина"
    )
    semester = models.IntegerField(verbose_name="Семестр")
    year = models.IntegerField(verbose_name="Курс")

    weeks = models.PositiveSmallIntegerField(
        default=18,
        validators=[MinValueValidator(18)],
        verbose_name="Количество недель"
    )

    lecture_hours = models.PositiveIntegerField(default=0, verbose_name="Лекционные часы")
    practice_hours = models.PositiveIntegerField(default=0, verbose_name="Практические часы")
    lab_hours = models.PositiveIntegerField(default=0, verbose_name="Лабораторные часы")

    exam_type = models.CharField(
        max_length=10,
        choices=EXAM_TYPES,
        null=True,
        blank=True,
        verbose_name="Вид отчетности"
    )

    class Meta:
        verbose_name = "Учебный план"
        verbose_name_plural = "Учебные планы"
        unique_together = ('academic_group', 'discipline', 'semester')

    def __str__(self):
        return f"{self.discipline.name} - {self.academic_group.name} ({self.semester} семестр)"

    @property
    def total_hours(self):
        return (self.lecture_hours or 0) + (self.practice_hours or 0) + (self.lab_hours or 0)

    @property
    def hours_per_week(self):
        if not self.weeks:
            return 0
        return round(self.total_hours / self.weeks, 2)

    @property
    def pairs_per_week(self):
        if not self.weeks:
            return 0
        return round((self.total_hours / 2) / self.weeks, 2)


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
    date = models.DateField(unique=True, verbose_name="Дата")
    weekday = models.IntegerField(choices=WEEKDAYS, verbose_name="День недели", default=1)
    is_working = models.BooleanField(default=True, verbose_name="Рабочий день")
    week_parity = models.CharField(max_length=10, choices=WEEK_PARITY, default='both', verbose_name="Четность недели")

    class Meta:
        ordering = ['date']
        verbose_name = "Учебный день"
        verbose_name_plural = "Учебные дни"

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

    student_group = models.ForeignKey(
        'StudentGroup',
        on_delete=models.CASCADE,
        related_name='schedule_entries'
    )
    teacher_assignment = models.ForeignKey(
        'TeacherAssignment',
        on_delete=models.CASCADE,
        related_name='schedule_entries'
    )
    room = models.ForeignKey(
        'Room',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='schedule_entries'
    )
    time_slot = models.ForeignKey(
        'TimeSlot',
        on_delete=models.PROTECT,
        related_name='schedule_entries'
    )
    working_day = models.ForeignKey(
        'WorkingDay',
        on_delete=models.PROTECT,
        related_name='schedule_entries'
    )
    week_parity = models.CharField(
        max_length=10,
        choices=WEEK_PARITY_CHOICES,
        default='both'
    )
    is_cancelled = models.BooleanField(default=False)
    replacement = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replacements'
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

        # 1. Нельзя ставить занятие в нерабочий день
        if self.working_day and not self.working_day.is_working:
            errors['working_day'] = 'Нельзя ставить занятие в нерабочий день.'

        # 2. Если выбрана аудитория, проверяем вместимость
        if self.room and self.student_group:
            if self.room.capacity < self.student_group.student_count:
                errors['room'] = 'В аудитории недостаточно мест для этой группы.'

        # 3. Лабораторные только в lab / computer
        if self.room and self.teacher_assignment and self.teacher_assignment.lesson_type:
            lesson_name = self.teacher_assignment.lesson_type.name.lower()
            room_type = self.room.room_type.lower()

            if 'лаб' in lesson_name and room_type not in ['lab', 'computer']:
                errors['room'] = 'Лабораторные занятия можно проводить только в лаборатории или компьютерном классе.'

        # 4. Не больше 5 пар в день для одной группы
        if self.student_group and self.working_day:
            qs = ScheduleEntry.objects.filter(
                student_group=self.student_group,
                working_day=self.working_day,
                week_parity=self.week_parity,
                is_cancelled=False
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.count() >= 5:
                errors['student_group'] = 'Для одной учебной группы в день не должно быть больше 5 пар.'

        # 5. Не больше 5 пар в день для преподавателя
        if self.teacher_assignment and self.working_day:
            teacher = self.teacher_assignment.teacher
            qs = ScheduleEntry.objects.filter(
                teacher_assignment__teacher=teacher,
                working_day=self.working_day,
                week_parity=self.week_parity,
                is_cancelled=False
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.count() >= 5:
                errors['teacher_assignment'] = 'Преподаватель не может работать больше 5 пар в день.'

        # 6. Проверка четности недели
        if self.working_day and self.week_parity != 'both':
            if self.working_day.week_parity not in ['both', self.week_parity]:
                errors['week_parity'] = 'Чётность недели занятия не совпадает с чётностью рабочего дня.'

        # 7. Переходы между корпусами для группы и преподавателя
        if self.room and self.working_day and self.time_slot and self.student_group and self.teacher_assignment:
            def get_travel_minutes(from_building, to_building):
                if from_building.id == to_building.id:
                    return 0

                direct = BuildingDistance.objects.filter(
                    from_building=from_building,
                    to_building=to_building
                ).first()

                reverse = BuildingDistance.objects.filter(
                    from_building=to_building,
                    to_building=from_building
                ).first()

                dist = direct or reverse
                if not dist:
                    raise ValidationError(
                        {'room': f'Не задано расстояние между корпусами "{from_building.name}" и "{to_building.name}".'}
                    )
                return dist.minutes

            def minutes_between(start_time, end_time):
                return int(
                    (
                            datetime.combine(self.working_day.date, start_time)
                            - datetime.combine(self.working_day.date, end_time)
                    ).total_seconds() / 60
                )

            def check_transition(subject_q, label):
                previous_entry = (
                    ScheduleEntry.objects.filter(
                        working_day=self.working_day,
                        is_cancelled=False,
                    )
                    .filter(subject_q)
                    .exclude(pk=self.pk)
                    .filter(time_slot__end_time__lte=self.time_slot.start_time)
                    .select_related('room__building', 'time_slot')
                    .order_by('-time_slot__end_time')
                    .first()
                )

                if previous_entry and previous_entry.room and previous_entry.room.building_id != self.room.building_id:
                    gap = minutes_between(self.time_slot.start_time, previous_entry.time_slot.end_time)
                    travel = get_travel_minutes(previous_entry.room.building, self.room.building)
                    if travel > gap:
                        errors['room'] = (
                            f'Недостаточно времени на переход между корпусами для {label}. '
                            f'Нужно {travel} мин., есть {gap} мин.'
                        )

                next_entry = (
                    ScheduleEntry.objects.filter(
                        working_day=self.working_day,
                        is_cancelled=False,
                    )
                    .filter(subject_q)
                    .exclude(pk=self.pk)
                    .filter(time_slot__start_time__gte=self.time_slot.end_time)
                    .select_related('room__building', 'time_slot')
                    .order_by('time_slot__start_time')
                    .first()
                )

                if next_entry and next_entry.room and next_entry.room.building_id != self.room.building_id:
                    gap = minutes_between(next_entry.time_slot.start_time, self.time_slot.end_time)
                    travel = get_travel_minutes(self.room.building, next_entry.room.building)
                    if travel > gap:
                        errors['room'] = (
                            f'Недостаточно времени на переход между корпусами для {label}. '
                            f'Нужно {travel} мин., есть {gap} мин.'
                        )

            check_transition(Q(student_group=self.student_group), 'учебной группы')
            check_transition(Q(teacher_assignment__teacher=self.teacher_assignment.teacher), 'преподавателя')

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f'{self.student_group.name} — {self.teacher_assignment.discipline.name} '
            f'({self.working_day.date}, {self.time_slot.pair_number} пара)'
        )