from django.core.management.base import BaseCommand
from vcs.models import ChatbotDocument
from vcs.rag_engine import index_document

class Command(BaseCommand):
    help = 'Index all active ChatbotDocuments into Qdrant'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Re-index even if already indexed')

    def handle(self, *args, **options):
        qs = ChatbotDocument.objects.filter(is_active=True)
        if not options['force']:
            qs = qs.filter(indexed_at__isnull=True)

        self.stdout.write(f'Indexing {qs.count()} documents…\n')
        for doc in qs:
            try:
                n = index_document(doc)
                self.stdout.write(self.style.SUCCESS(f'  ✓ {doc.title} — {n} chunks'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ✗ {doc.title} — {e}'))

        self.stdout.write(self.style.SUCCESS('\nDone.'))