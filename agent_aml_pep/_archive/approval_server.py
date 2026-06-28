"""
approval_server.py — ScreenEdge Africa
Serveur Flask local — reçoit l'approbation de n8n et applique les changements GAFI.
Lancer une fois : python approval_server.py
"""

import sys, os, subprocess
sys.stdout.reconfigure(encoding="utf-8")

from flask import Flask, request, jsonify

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(BASE, ".venv", "Scripts", "python.exe")

@app.route("/apply-gafi", methods=["POST"])
def apply():
    data = request.json or {}
    action = data.get("action", "")
    if action != "approve":
        return jsonify({"status": "rejected"}), 200
    result = subprocess.run(
        [PYTHON, os.path.join(BASE, "apply_changes.py")],
        capture_output=True, text=True, cwd=BASE
    )
    print(result.stdout)
    return jsonify({"status": "applied", "output": result.stdout}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    print("Approval server en écoute sur http://localhost:5050")
    app.run(host="0.0.0.0", port=5050)
