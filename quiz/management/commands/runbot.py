from django.core.management.base import BaseCommand
from quiz.bot import run_bot

class Command(BaseCommand):
    help = "Запускает Telegram-бот (async)"

    def handle(self, *args, **options):
        run_bot()
