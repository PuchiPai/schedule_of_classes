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
admin.site.register(ScheduleEntry)