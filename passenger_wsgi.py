import os
import sys
import glob

# 1. Add current project directory to sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# 2. Automatically locate and add virtualenv site-packages to sys.path
# Check local folders: env, venv, .env, .venv
for venv_name in ['env', 'venv', '.env', '.venv']:
    candidate_sp = glob.glob(os.path.join(CURRENT_DIR, venv_name, 'lib', 'python*', 'site-packages'))
    for sp in candidate_sp:
        if sp not in sys.path:
            sys.path.insert(0, sp)

# Check cPanel global virtualenv directory: ~/virtualenv/<app_name>/<py_ver>/lib/python*/site-packages
home_dir = os.path.expanduser('~')
cpanel_sp = glob.glob(os.path.join(home_dir, 'virtualenv', '*', '*', 'lib', 'python*', 'site-packages'))
for sp in cpanel_sp:
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Also check site-packages of the active python interpreter
if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
    prefix_sp = glob.glob(os.path.join(sys.prefix, 'lib', 'python*', 'site-packages'))
    for sp in prefix_sp:
        if sp not in sys.path:
            sys.path.insert(0, sp)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

# 3. Robust WSGI Application Loader with friendly error reporting for cPanel
try:
    from myproject.wsgi import application
except Exception:
    import traceback
    error_traceback = traceback.format_exc()

    def application(environ, start_response):
        start_response('500 Internal Server Error', [('Content-Type', 'text/html; charset=utf-8')])
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Bazaarpe - cPanel Startup Error</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 30px; margin: 0; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 28px; max-width: 900px; margin: 20px auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #334155; }}
        h1 {{ color: #f43f5e; font-size: 22px; margin-top: 0; }}
        pre {{ background: #090d16; color: #38bdf8; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; line-height: 1.5; font-family: monospace; border: 1px solid #1e293b; }}
        .help {{ color: #94a3b8; font-size: 14px; margin-top: 20px; line-height: 1.6; border-top: 1px solid #334155; padding-top: 16px; }}
        code {{ background: #334155; padding: 2px 6px; border-radius: 4px; color: #f1f5f9; }}
        ol {{ padding-left: 20px; }}
        li {{ margin-bottom: 8px; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Bazaarpe Application Startup Error</h1>
        <p>A Python exception occurred while initializing Django via Phusion Passenger:</p>
        <pre>{error_traceback}</pre>
        <div class="help">
            <strong>How to fix this in cPanel:</strong>
            <ol>
                <li><strong>Install Dependencies</strong>: In cPanel, go to <em>Setup Python App</em> &rarr; Click your app &rarr; in <em>Configuration files</em> enter <code>requirements.txt</code> &rarr; Click <strong>Run Pip Install</strong>.</li>
                <li><strong>Python Version</strong>: Ensure your Python version is <strong>3.10, 3.11, or 3.12</strong> (Django 5 requires Python 3.10+).</li>
                <li><strong>Permissions</strong>: Ensure <code>db.sqlite3</code> and the application directory have write permissions.</li>
            </ol>
        </div>
    </div>
</body>
</html>"""
        return [html.encode('utf-8')]
