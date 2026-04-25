from .models import UISettings

def site_settings(request):
    return {'ui_settings': UISettings.objects.first()}