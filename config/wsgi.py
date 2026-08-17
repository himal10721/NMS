"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# tell Django which settings module to use for WSGI requests
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# create the WSGI application used by WSGI servers
application = get_wsgi_application()
