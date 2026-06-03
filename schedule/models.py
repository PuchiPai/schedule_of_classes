from django.db import models

class Lesson(models.Model):
    name = models.CharField(max_length=100)
    teacher = models.CharField(max_length=100)
    day = models.CharField(max_length=20)
    time = models.TimeField()

    def __str__(self):
        return self.name