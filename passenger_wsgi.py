import os
import sys
import traceback

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_LOG = os.path.join(CURRENT_DIR, 'passenger_debug.log')

def write_debug(msg):
    try:
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            import datetime
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{now}] {msg}\n")
    except Exception:
        pass

write_debug("--- Passenger Startup Initiated ---")
write_debug(f"Python executable: {sys.executable}")
write_debug(f"Python version: {sys.version}")

# Ensure project root is in sys.path
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# Dynamically locate this specific app's virtualenv in cPanel
app_folder_name = os.path.basename(CURRENT_DIR)
home_dir = os.path.expanduser('~')
virtualenv_base = os.path.join(home_dir, 'virtualenv')

if os.path.isdir(virtualenv_base):
    for root, dirs, files in os.walk(virtualenv_base):
        if os.path.basename(root) == 'site-packages':
            if app_folder_name.lower() in root.lower() or 'bazaarpe' in root.lower():
                if root not in sys.path:
                    sys.path.insert(0, root)
                    write_debug(f"Added virtualenv site-packages: {root}")

# Also check for local virtualenv in CURRENT_DIR (e.g. venv, env)
for v_name in ['venv', 'env', '.venv']:
    local_sp = os.path.join(CURRENT_DIR, v_name, 'lib')
    if os.path.isdir(local_sp):
        for root, dirs, files in os.walk(local_sp):
            if os.path.basename(root) == 'site-packages' and root not in sys.path:
                sys.path.insert(0, root)
                write_debug(f"Added local site-packages: {root}")

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

django_app = None
init_error = None

try:
    from django.core.wsgi import get_wsgi_application
    django_app = get_wsgi_application()
    write_debug("Django WSGI application loaded successfully.")
except Exception as e:
    init_error = traceback.format_exc()
    write_debug(f"Django Initialization Error:\n{init_error}")


def application(environ, start_response):
    """
    WSGI Entry Point with guaranteed 200 OK error visualizer.
    Prevents LiteSpeed/Passenger 'Incomplete response received from application'.
    """
    if init_error:
        output = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Bazaarpe - cPanel Startup Error</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0b1120; color: #f8fafc; padding: 24px; margin: 0; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 28px; max-width: 900px; margin: 20px auto; box-shadow: 0 10px 30px rgba(0,0,0,0.6); border: 1px solid #334155; }}
        h1 {{ color: #f43f5e; font-size: 22px; margin-top: 0; }}
        pre {{ background: #030712; color: #38bdf8; padding: 18px; border-radius: 8px; overflow-x: auto; font-size: 13px; line-height: 1.6; font-family: 'JetBrains Mono', Consolas, monospace; border: 1px solid #1e293b; }}
        .meta {{ background: #0f172a; padding: 14px; border-radius: 8px; font-size: 12px; color: #94a3b8; margin-bottom: 20px; border: 1px solid #334155; }}
        .help {{ color: #cbd5e1; font-size: 14px; line-height: 1.6; border-top: 1px solid #334155; padding-top: 18px; margin-top: 20px; }}
        code {{ background: #334155; padding: 2px 6px; border-radius: 4px; color: #f1f5f9; font-size: 12px; }}
        ol {{ padding-left: 20px; }}
        li {{ margin-bottom: 10px; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Bazaarpe Application Initialization Error</h1>
        <div class="meta">
            <strong>Python:</strong> {sys.version.split()[0]} ({sys.executable})<br>
            <strong>App Directory:</strong> {CURRENT_DIR}<br>
            <strong>Log File:</strong> {DEBUG_LOG}
        </div>
        <p>Django failed to initialize with the following exception:</p>
        <pre>{init_error}</pre>
        <div class="help">
            <strong>How to resolve this in cPanel:</strong>
            <ol>
                <li><strong>Install Requirements</strong>: In cPanel, open <em>Setup Python App</em> &rarr; Click your application &rarr; In <em>Configuration files</em> add <code>requirements.txt</code> &rarr; Click <strong>Run Pip Install</strong>.</li>
                <li><strong>Check Python Version</strong>: Ensure your Python version is <strong>3.10, 3.11, or 3.12</strong> (Django 5 requires Python 3.10+).</li>
                <li><strong>Run Migrations</strong>: Open the cPanel Terminal and run <code>python manage.py migrate</code>.</li>
                <li><strong>Database File Permissions</strong>: Ensure <code>db.sqlite3</code> and the application directory have write permissions (<code>chmod 664 db.sqlite3</code>).</li>
            </ol>
        </div>
    </div>
</body>
</html>""".encode('utf-8')
        start_response('200 OK', [
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Length', str(len(output)))
        ])
        return [output]

    try:
        return django_app(environ, start_response)
    except Exception:
        err_msg = traceback.format_exc()
        write_debug(f"Request Runtime Error:\n{err_msg}")
        output = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Bazaarpe - Request Error</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; background: #0b1120; color: #f8fafc; padding: 24px; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 28px; max-width: 900px; margin: 20px auto; border: 1px solid #334155; }}
        pre {{ background: #030712; color: #f43f5e; padding: 18px; border-radius: 8px; overflow-x: auto; font-size: 13px; line-height: 1.6; }}
    </style>
</head>
<body>
    <div class="card">
        <h1 style="color:#f43f5e; margin-top:0;">Request Runtime Error</h1>
        <pre>{err_msg}</pre>
    </div>
</body>
</html>""".encode('utf-8')
        start_response('200 OK', [
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Length', str(len(output)))
        ])
        return [output]
