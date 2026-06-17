"""
Management command: preload_models
Usage: python manage.py preload_models --model m3e-base
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "预加载嵌入模型和 FAISS 索引"

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            default="m3e-base",
            choices=list(settings.MODEL_CONFIGS.keys()),
            help="要预加载的模型名称",
        )
        parser.add_argument(
            "--abstract-mode",
            default="own",
            choices=["own", "external"],
            help="摘要模式",
        )

    def handle(self, *args, **options):
        from core.model_loader import get_model, get_data

        model_name = options["model"]
        abstract_mode = options["abstract_mode"]

        self.stdout.write(f"预加载模型: {model_name} ...")
        get_model(model_name)
        self.stdout.write(self.style.SUCCESS(f"模型 {model_name} 加载完成"))

        self.stdout.write(f"预加载索引 (abstract_mode={abstract_mode}) ...")
        get_data(model_name, abstract_mode)
        self.stdout.write(self.style.SUCCESS("索引加载完成"))
