"""
upload_n8n_workflow.py — ScreenEdge Africa
Upload automatique du workflow GAFI Monitor dans n8n via API.
"""

import sys, os, json, requests
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv(override=True)

API_KEY  = os.getenv("N8N_API_KEY")
BASE_URL = "http://localhost:5679/api/v1"
HEADERS  = {"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}

# ── Workflow GAFI Monitor ──────────────────────────────────────────────────
WORKFLOW = {
    "name": "GAFI Monitor — ScreenEdge Africa",
    "settings": {
        "executionOrder": "v1",
        "saveManualExecutions": True,
        "callerPolicy": "workflowsFromSameOwner"
    },
    "nodes": [
        {
            "id": "node-webhook-trigger",
            "name": "Webhook GAFI",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [200, 300],
            "parameters": {
                "path": "gafi-monitor",
                "httpMethod": "POST",
                "responseMode": "onReceived",
                "responseData": "allEntries"
            }
        },
        {
            "id": "node-send-email",
            "name": "Email Alerte GAFI",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2,
            "position": [500, 200],
            "parameters": {
                "operation": "send",
                "sendTo": "gatsoundoujuniior@gmail.com",
                "subject": "=⚠️ [ScreenEdge Africa] GAFI — {{ $json.nb_changements }} changement(s) détecté(s) — {{ $json.date }}",
                "emailType": "html",
                "message": "=<html><body style='font-family:Arial,sans-serif;max-width:600px;margin:auto'><div style='background:#1a1a2e;color:white;padding:20px;border-radius:8px 8px 0 0'><h2 style='margin:0'>ScreenEdge Africa — Alerte GAFI</h2><p style='opacity:.8'>Monitoring automatique — {{ $json.date }}</p></div><div style='background:#f8f9fa;padding:20px;border:1px solid #dee2e6'><h3 style='color:#dc3545'>⚠️ {{ $json.nb_changements }} changement(s) détecté(s)</h3><table style='width:100%;border-collapse:collapse'><tr style='background:#343a40;color:white'><th style='padding:8px;text-align:left'>Pays</th><th style='padding:8px;text-align:left'>Ancien</th><th style='padding:8px;text-align:left'>Nouveau</th></tr>{{ $json.changements.map(c => `<tr style='background:#fff3cd'><td style='padding:8px;font-weight:bold'>${c.pays} (${c.code})</td><td style='padding:8px'>${c.ancien}</td><td style='padding:8px;color:#155724;font-weight:bold'>${c.nouveau}</td></tr>`).join('') }}</table><p style='margin-top:20px;font-size:14px'>Cliquez ci-dessous pour valider ou refuser la mise à jour du référentiel :</p><p><a href='{{ $execution.resumeUrl }}?action=approve' style='background:#198754;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;margin-right:12px'>✅ Valider</a><a href='{{ $execution.resumeUrl }}?action=reject' style='background:#dc3545;color:white;padding:12px 24px;border-radius:6px;text-decoration:none'>❌ Refuser</a></p></div><div style='background:#e9ecef;padding:12px;border-radius:0 0 8px 8px;font-size:12px;color:#6c757d;text-align:center'>ScreenEdge Africa — Agent AML/PPE v8.1</div></body></html>"
            },
            "credentials": {
                "gmailOAuth2": {"id": "gmail-creds", "name": "Gmail"}
            }
        },
        {
            "id": "node-whatsapp",
            "name": "WhatsApp Alerte",
            "type": "n8n-nodes-base.twilio",
            "typeVersion": 1,
            "position": [500, 420],
            "parameters": {
                "operation": "send",
                "from": "whatsapp:+14155238886",
                "to": "=whatsapp:{{ $env.WHATSAPP_NUMBER }}",
                "message": "=*ScreenEdge Africa — Alerte GAFI*\n\n⚠️ {{ $json.nb_changements }} changement(s) détecté(s) le {{ $json.date }}\n\n{{ $json.changements.map(c => `• ${c.pays} : ${c.ancien} → ${c.nouveau}`).join('\\n') }}\n\n👉 Vérifiez votre email pour valider ou refuser la mise à jour."
            },
            "credentials": {
                "twilioApi": {"id": "twilio-creds", "name": "Twilio"}
            }
        },
        {
            "id": "node-wait",
            "name": "Attente Validation",
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1,
            "position": [800, 300],
            "parameters": {
                "resume": "webhook",
                "options": {}
            },
            "webhookId": "gafi-approval"
        },
        {
            "id": "node-check-action",
            "name": "Approuvé ?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [1050, 300],
            "parameters": {
                "conditions": {
                    "string": [{
                        "value1": "={{ $json.query.action }}",
                        "operation": "equals",
                        "value2": "approve"
                    }]
                }
            }
        },
        {
            "id": "node-apply",
            "name": "Appliquer changements",
            "type": "n8n-nodes-base.executeCommand",
            "typeVersion": 1,
            "position": [1300, 200],
            "parameters": {
                "command": "cd /c/Users/pc/Downloads/agent_aml_pep && .venv/Scripts/python.exe apply_changes.py"
            }
        },
        {
            "id": "node-confirm-email",
            "name": "Email Confirmation",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2,
            "position": [1550, 200],
            "parameters": {
                "operation": "send",
                "sendTo": "gatsoundoujuniior@gmail.com",
                "subject": "=✅ [ScreenEdge Africa] Référentiel GAFI mis à jour — {{ $now.format('dd/MM/yyyy') }}",
                "emailType": "html",
                "message": "<html><body style='font-family:Arial,sans-serif'><div style='background:#198754;color:white;padding:20px;border-radius:8px'><h2>✅ Référentiel GAFI mis à jour</h2><p>Les changements ont été validés et appliqués au référentiel AML/PPE ScreenEdge Africa.</p></div></body></html>"
            },
            "credentials": {
                "gmailOAuth2": {"id": "gmail-creds", "name": "Gmail"}
            }
        },
        {
            "id": "node-reject-email",
            "name": "Email Refus",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2,
            "position": [1300, 420],
            "parameters": {
                "operation": "send",
                "sendTo": "gatsoundoujuniior@gmail.com",
                "subject": "=❌ [ScreenEdge Africa] Mise à jour GAFI refusée — {{ $now.format('dd/MM/yyyy') }}",
                "emailType": "html",
                "message": "<html><body style='font-family:Arial,sans-serif'><div style='background:#dc3545;color:white;padding:20px;border-radius:8px'><h2>❌ Mise à jour refusée</h2><p>Les changements GAFI détectés ont été refusés. Le référentiel reste inchangé.</p></div></body></html>"
            },
            "credentials": {
                "gmailOAuth2": {"id": "gmail-creds", "name": "Gmail"}
            }
        }
    ],
    "connections": {
        "Webhook GAFI": {
            "main": [[
                {"node": "Email Alerte GAFI", "type": "main", "index": 0},
                {"node": "WhatsApp Alerte",   "type": "main", "index": 0}
            ]]
        },
        "Email Alerte GAFI": {
            "main": [[{"node": "Attente Validation", "type": "main", "index": 0}]]
        },
        "WhatsApp Alerte": {
            "main": [[{"node": "Attente Validation", "type": "main", "index": 0}]]
        },
        "Attente Validation": {
            "main": [[{"node": "Approuvé ?", "type": "main", "index": 0}]]
        },
        "Approuvé ?": {
            "main": [
                [{"node": "Appliquer changements", "type": "main", "index": 0}],
                [{"node": "Email Refus",            "type": "main", "index": 0}]
            ]
        },
        "Appliquer changements": {
            "main": [[{"node": "Email Confirmation", "type": "main", "index": 0}]]
        }
    }
}


def upload():
    print("Upload du workflow GAFI Monitor vers n8n...\n")
    r = requests.post(f"{BASE_URL}/workflows", headers=HEADERS, json=WORKFLOW)
    if r.status_code in (200, 201):
        data = r.json()
        wf_id  = data.get("id")
        wf_url = f"http://localhost:5679/workflow/{wf_id}"
        print(f"Workflow créé : {data.get('name')}")
        print(f"ID            : {wf_id}")
        print(f"URL           : {wf_url}")
        print("\nProchaines étapes dans n8n :")
        print("  1. Configurer les credentials Gmail (OAuth2)")
        print("  2. Configurer les credentials Twilio (WhatsApp)")
        print("  3. Activer le workflow")
    else:
        print(f"Erreur {r.status_code} : {r.text[:300]}")


if __name__ == "__main__":
    upload()
