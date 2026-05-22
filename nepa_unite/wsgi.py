import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nepa_unite.settings.production")

application = get_wsgi_application()
