"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# tell Django which settings module to use for ASGI requests
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# create the ASGI application used by ASGI servers
application = get_asgi_application()
