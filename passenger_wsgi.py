import os
import sys

# Set up current directory on Python path for cPanel Passenger WSGI
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

from myproject.wsgi import application
