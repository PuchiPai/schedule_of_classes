from django.contrib import admin
from .models import *

admin.site.register(Department)
admin.site.register(Teacher)
admin.site.register(AcademicGroup)
admin.site.register(StudentGroup)
admin.site.register(Building)
admin.site.register(Room)
admin.site.register(Discipline)
admin.site.register(LessonType)
admin.site.register(Curriculum)
admin.site.register(TeacherAssignment)
admin.site.register(TimeSlot)
admin.site.register(WorkingDay)

@admin.register(ScheduleEntry)
class ScheduleEntryAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'student_group',
        'teacher_assignment',
        'room',
        'working_day',
        'time_slot',
        'week_parity',
        'is_cancelled',
    )
    list_filter = (
        'working_day',
        'week_parity',
        'is_cancelled',
        'student_group',
        'room',
    )
    search_fields = (
        'student_group__name',
        'teacher_assignment__teacher__full_name',
        'teacher_assignment__discipline__name',
        'room__name',
    )
    list_select_related = (
        'student_group',
        'teacher_assignment',
        'room',
        'time_slot',
        'working_day',
    )