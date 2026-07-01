import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Vérifier l'usage Tavily dans api_usage.json
_, o, _ = ssh.exec_command("cat /root/screen_edge/api_usage.json 2>/dev/null || echo 'FICHIER ABSENT'")
print("=== api_usage.json ===")
print(o.read().decode("utf-8", errors="replace"))

# Test direct Tavily
_, o, _ = ssh.exec_command("""cd /root/screen_edge && python3 -c "
import os; from dotenv import load_dotenv; load_dotenv()
from langchain_tavily import TavilySearch
tool = TavilySearch(max_results=1, tavily_api_key=os.getenv('TAVILY_API_KEY'))
try:
    r = tool.invoke({'query': 'test Maroc'})
    print('Tavily OK :', str(r)[:100])
except Exception as e:
    print('Tavily ERREUR :', str(e)[:200])
" 2>&1""")
print("=== Test Tavily direct ===")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()
