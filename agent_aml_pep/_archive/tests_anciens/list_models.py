import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groq import Groq
from dotenv import load_dotenv
load_dotenv()
client = Groq()
models = client.models.list()
for m in sorted(models.data, key=lambda x: x.id):
    print(m.id)
