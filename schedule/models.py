from django.db import models

# 1. Подразделения (иерархия: Университет → Школа → Кафедра)
class Department(models.Model):
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.name

# 2. Преподаватели
class Teacher(models.Model):
    full_name = models.CharField(max_length=255)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    academic_degree = models.CharField(max_length=100, blank=True)  # учёная степень
    academic_title = models.CharField(max_length=100, blank=True)   # учёное звание
    position = models.CharField(max_length=100)                     # должность
    max_hours_per_day = models.IntegerField(default=8)              # не более 5 пар

    def __str__(self):
        return self.full_name

# 3. Академическая группа (номер группы в направлении)
class AcademicGroup(models.Model):
    name = models.CharField(max_length=50, unique=True)
    direction = models.CharField(max_length=200)  # направление подготовки

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
    name = models.CharField(max_length=50, unique=True)
    group_type = models.CharField(max_length=20, choices=GROUP_TYPES)
    academic_group = models.ForeignKey(AcademicGroup, on_delete=models.CASCADE, null=True, blank=True)
    student_count = models.PositiveIntegerField()

    def __str__(self):
        return self.name

# 5. Корпус
class Building(models.Model):
    name = models.CharField(max_length=100)
    distance_to_other = models.IntegerField(default=0)  # время перемещения в минутах

    def __str__(self):
        return self.name

# 6. Аудитория
class Room(models.Model):
    ROOM_TYPES = [
        ('lecture', 'Лекционная'),
        ('practice', 'Практическая'),
        ('lab', 'Лаборатория'),
        ('computer', 'Компьютерный класс'),
        ('hall', 'Спортивный зал'),
        ('online', 'Онлайн'),
    ]
    name = models.CharField(max_length=50, unique=True)
    building = models.ForeignKey(Building, on_delete=models.PROTECT)
    capacity = models.PositiveIntegerField()
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES)

    def __str__(self):
        return f"{self.name} ({self.get_room_type_display()})"

# 7. Дисциплина
class Discipline(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name

# 8. Тип занятия (справочник)
class LessonType(models.Model):
    name = models.CharField(max_length=50)  # лекция, практика, лаба, зачёт, экзамен, консультация
    default_duration_minutes = models.IntegerField()

    def __str__(self):
        return self.name

# 9. Учебный план (на семестр)
class Curriculum(models.Model):
    EXAM_TYPES = [
        ('exam', 'Экзамен'),
        ('credit', 'Зачёт'),
    ]
    academic_group = models.ForeignKey(AcademicGroup, on_delete=models.CASCADE)
    discipline = models.ForeignKey(Discipline, on_delete=models.CASCADE)
    semester = models.IntegerField()          # 1-8
    year = models.IntegerField()              # 1-4
    hours_per_week = models.IntegerField()    # трудоёмкость (часов в неделю)
    weeks = models.IntegerField(default=18)   # длительность семестра
    exam_type = models.CharField(max_length=10, choices=EXAM_TYPES, null=True, blank=True)

    def __str__(self):
        return f"{self.discipline.name} - {self.academic_group.name} ({self.semester} семестр)"

# 10. Учебное поручение (какой преподаватель ведёт какую дисциплину)
class TeacherAssignment(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    discipline = models.ForeignKey(Discipline, on_delete=models.CASCADE)
    lesson_type = models.ForeignKey(LessonType, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.teacher.full_name} - {self.discipline.name} ({self.lesson_type.name})"

# 11. Время проведения пар (справочник)
class TimeSlot(models.Model):
    pair_number = models.IntegerField()  # 1-8
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"{self.pair_number} пара: {self.start_time} - {self.end_time}"

# 12. Рабочие дни (производственный календарь)
class WorkingDay(models.Model):
    WEEK_PARITY = [
        ('even', 'Чётная неделя'),
        ('odd', 'Нечётная неделя'),
        ('both', 'Обе недели'),
    ]
    date = models.DateField()
    is_working = models.BooleanField(default=True)
    week_parity = models.CharField(max_length=10, choices=WEEK_PARITY, default='both')
    is_holiday = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.date} ({'рабочий' if self.is_working else 'выходной'})"

# 13. Занятие в расписании (главная таблица)
class ScheduleEntry(models.Model):
    student_group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE)
    teacher_assignment = models.ForeignKey(TeacherAssignment, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, null=True, blank=True)  # null = онлайн
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE)
    working_day = models.ForeignKey(WorkingDay, on_delete=models.CASCADE)
    week_parity = models.CharField(max_length=10, choices=WorkingDay.WEEK_PARITY, default='both')
    is_cancelled = models.BooleanField(default=False)
    replacement = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)  # перенос

    class Meta:
        constraints = [
            # Ограничение: аудитория не может быть занята в одно время
            models.UniqueConstraint(fields=['room', 'time_slot', 'working_day', 'week_parity'], name='unique_room_slot'),
            # Ограничение: преподаватель не может быть в двух местах
            models.UniqueConstraint(fields=['teacher_assignment', 'time_slot', 'working_day', 'week_parity'], name='unique_teacher_slot'),
            # Ограничение: группа не может быть в двух местах
            models.UniqueConstraint(fields=['student_group', 'time_slot', 'working_day', 'week_parity'], name='unique_group_slot'),
        ]

    def __str__(self):
        return f"{self.student_group.name} - {self.teacher_assignment.discipline.name} ({self.working_day.date}, {self.time_slot})"