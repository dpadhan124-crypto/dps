import os
import sys
import time
import threading
import subprocess
import importlib.util
from collections import deque
from functools import wraps
from flask import Flask, request, Response, jsonify, render_template_string
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

# ==========================================
# 1. ADD YOUR BOTS HERE
# ==========================================
# Just upload your .py file and add its exact name to this list.
BOTS_TO_RUN = [
    "master_bot.py",
    "bot1.py",
    "live.py"
]

# Admin Login for the Dashboard
ADMIN_USER = os.getenv("DASHBOARD_USER", "admin")
ADMIN_PASS = os.getenv("DASHBOARD_PASS", "1234")

# ==========================================
# 2. CORE DASHBOARD SETUP
# ==========================================
manager_app = Flask(__name__)

def check_auth(username, password):
    return username == ADMIN_USER and password == ADMIN_PASS

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response('Login Required', 401, {'WWW-Authenticate': 'Basic realm="Login"'})
        return f(*args, **kwargs)
    return decorated

class BotManager:
    def __init__(self):
        self.logs = {bot: deque(maxlen=50) for bot in BOTS_TO_RUN}
        self.processes = {}
        self.status = {bot: "Stopped" for bot in BOTS_TO_RUN}

    def read_logs(self, name, process):
        try:
            for line in iter(process.stdout.readline, b''):
                self.logs[name].append(line.decode('utf-8').strip())
        except Exception:
            pass
        finally:
            process.stdout.close()
            if self.status.get(name) == "Running":
                self.status[name] = "Crashed"
                self.logs[name].append(f"[SYSTEM] {name} exited unexpectedly.")

    def start_bot(self, name):
        if self.status.get(name) == "Running": return
        if not os.path.exists(name):
            self.logs[name].append(f"[SYSTEM] Error: {name} not found.")
            return

        p = subprocess.Popen(
            [sys.executable, name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )
        self.processes[name] = p
        self.status[name] = "Running"
        self.logs[name].append(f"[SYSTEM] Started {name}")
        threading.Thread(target=self.read_logs, args=(name, p), daemon=True).start()

    def stop_bot(self, name):
        if name in self.processes and self.status[name] == "Running":
            self.processes[name].terminate()
            self.status[name] = "Stopped"
            self.logs[name].append(f"[SYSTEM] Stopped {name}")

manager = BotManager()

# ==========================================
# 3. WEB ROUTES & UI
# ==========================================
@manager_app.route('/')
@requires_auth
def dashboard():
    live_code = open("live.py", "r").read() if os.path.exists("live.py") else ""
    return render_template_string(HTML_TEMPLATE, bots=BOTS_TO_RUN, live_code=live_code)

@manager_app.route('/api/status')
@requires_auth
def get_status():
    return jsonify({"status": manager.status, "logs": {k: list(v) for k, v in manager.logs.items()}})

@manager_app.route('/api/action', methods=['POST'])
@requires_auth
def action():
    data = request.json
    action, bot_name = data.get('action'), data.get('bot')
    if action == 'start': manager.start_bot(bot_name)
    elif action == 'stop': manager.stop_bot(bot_name)
    return jsonify({"success": True})

@manager_app.route('/api/save_live', methods=['POST'])
@requires_auth
def save_live():
    with open("live.py", "w") as f:
        f.write(request.json.get('code', ''))
    manager.stop_bot("live.py")
    time.sleep(1)
    manager.start_bot("live.py")
    return jsonify({"success": True})

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Control Center</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
</head>
<body class="bg-gray-100 text-gray-800 font-sans">
    <nav class="bg-blue-600 text-white p-4 shadow-md">
        <h1 class="text-xl font-bold">Bot Control Center</h1>
        <p class="text-sm mt-1">Upload your file -> Add to list -> Manage here.</p>
    </nav>
    <div class="p-4 max-w-4xl mx-auto space-y-6">
        <div id="bot-container" class="grid grid-cols-1 md:grid-cols-2 gap-4">
            {% for bot in bots %}
            <div class="bg-white p-4 rounded-lg shadow border-l-4 border-gray-400" id="card-{{ bot | replace('.', '-') }}">
                <div class="flex justify-between items-center mb-2">
                    <h2 class="text-lg font-semibold">{{ bot }}</h2>
                    <span id="badge-{{ bot | replace('.', '-') }}" class="px-2 py-1 rounded text-xs font-bold bg-gray-200 text-gray-700">Loading...</span>
                </div>
                <div class="flex space-x-2 mb-3">
                    <button onclick="sendAction('{{ bot }}', 'start')" class="bg-green-500 text-white px-3 py-1 rounded shadow text-sm w-1/2">Start</button>
                    <button onclick="sendAction('{{ bot }}', 'stop')" class="bg-red-500 text-white px-3 py-1 rounded shadow text-sm w-1/2">Stop</button>
                </div>
                <div class="bg-gray-900 text-green-400 p-2 rounded h-32 overflow-y-auto text-xs font-mono" id="log-{{ bot | replace('.', '-') }}">Logs loading...</div>
            </div>
            {% endfor %}
        </div>
        <div class="bg-white p-4 rounded-lg shadow">
            <h2 class="text-lg font-semibold mb-2">live.py Editor</h2>
            <textarea id="live-code" class="w-full h-48 p-2 border rounded font-mono text-sm bg-gray-50">{{ live_code }}</textarea>
            <button onclick="saveLiveCode()" class="mt-2 bg-blue-600 text-white px-4 py-2 rounded shadow w-full">Save & Restart Live Bot</button>
        </div>
    </div>
    <script>
        function sendAction(bot, action) { fetch('/api/action', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({bot: bot, action: action}) }); }
        function saveLiveCode() { fetch('/api/save_live', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: document.getElementById('live-code').value}) }).then(() => alert("Restarting live.py!")); }
        function updateStatus() {
            fetch('/api/status').then(r => r.json()).then(data => {
                for (const [bot, status] of Object.entries(data.status)) {
                    const safeId = bot.replace('.', '-');
                    const badge = document.getElementById('badge-' + safeId);
                    const logBox = document.getElementById('log-' + safeId);
                    const card = document.getElementById('card-' + safeId);
                    if(!badge) continue;
                    
                    badge.innerText = status;
                    if(status === 'Running') { badge.className = 'px-2 py-1 rounded text-xs font-bold bg-green-200 text-green-800'; card.className = 'bg-white p-4 rounded-lg shadow border-l-4 border-green-500'; } 
                    else if (status === 'Crashed') { badge.className = 'px-2 py-1 rounded text-xs font-bold bg-red-200 text-red-800'; card.className = 'bg-white p-4 rounded-lg shadow border-l-4 border-red-500'; } 
                    else { badge.className = 'px-2 py-1 rounded text-xs font-bold bg-gray-200 text-gray-800'; card.className = 'bg-white p-4 rounded-lg shadow border-l-4 border-gray-400'; }
                    logBox.innerHTML = data.logs[bot].join('<br>');
                    logBox.scrollTop = logBox.scrollHeight;
                }
            });
        }
        setInterval(updateStatus, 1500);
    </script>
</body>
</html>
"""

# ==========================================
# 4. AUTO-MOUNT SUB-WEB APPS & LAUNCH
# ==========================================
# Automatically finds Flask 'app' objects in your bot files and maps them to /bot_name
route_map = {}
for bot_file in BOTS_TO_RUN:
    if os.path.exists(bot_file):
        module_name = bot_file.replace('.py', '')
        try:
            spec = importlib.util.spec_from_file_location(module_name, bot_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, 'app'):
                route_map[f'/{module_name}'] = mod.app
                print(f"[Gateway] Mapped Web App for {bot_file} to /{module_name}")
        except Exception:
            pass # Fails silently if no web app exists in the file, which is perfectly fine

application = DispatcherMiddleware(manager_app, route_map)

if __name__ == "__main__":
    for bot in BOTS_TO_RUN:
        manager.start_bot(bot)
    
    port = int(os.environ.get('PORT', 8080))
    print(f"Server starting on port {port}...")
    run_simple('0.0.0.0', port, application, threaded=True)
