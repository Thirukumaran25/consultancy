from django.apps import AppConfig


class VcsConfig(AppConfig):
    name = 'vcs'

    def ready(self):
        import vcs.signals