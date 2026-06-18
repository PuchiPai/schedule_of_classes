from django.core.management.base import BaseCommand, CommandError

from schedule.models import AcademicGroup
from schedule.services import generate_demo_schedule_from_curriculum


class Command(BaseCommand):
    help = 'Генерация демо-расписания из учебного плана'

    def add_arguments(self, parser):
        parser.add_argument(
            '--academic-group',
            type=str,
            required=True,
            help='Название академической группы, например: ПИ-221',
        )
        parser.add_argument(
            '--semester',
            type=int,
            required=True,
            help='Семестр, например: 3',
        )
        parser.add_argument(
            '--year',
            type=int,
            required=False,
            default=None,
            help='Курс, например: 2',
        )
        parser.add_argument(
            '--week-parity',
            type=str,
            choices=['both', 'even', 'odd'],
            default='both',
            help='Чётность недели',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Удалить старые записи расписания для этой академической группы перед генерацией',
        )

    def handle(self, *args, **options):
        academic_group_name = options['academic_group']
        semester = options['semester']
        year = options['year']
        week_parity = options['week_parity']
        clear_existing = options['clear']

        academic_group = AcademicGroup.objects.filter(name=academic_group_name).first()
        if not academic_group:
            raise CommandError(f'Академическая группа "{academic_group_name}" не найдена.')

        try:
            created = generate_demo_schedule_from_curriculum(
                academic_group=academic_group,
                semester=semester,
                year=year,
                week_parity=week_parity,
                clear_existing=clear_existing,
            )
        except Exception as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.SUCCESS(
                f'Готово. Создано записей расписания: {len(created)}'
            )
        )