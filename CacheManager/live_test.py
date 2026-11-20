import urllib.request
import urllib.parse
import json

BASE = "http://localhost:8001"

def post(endpoint, params=None):
    url = f"{BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def get(endpoint):
    req = urllib.request.Request(f"{BASE}{endpoint}", method="GET")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

print("=" * 60)
print("TESTE EM DIRETO AO SERVIÇO DOCKER (http://localhost:8001)")
print("=" * 60)

# 1. Warm region
print("\n[Passo 1] Forçar aquecimento da região 'eu-west-3'...")
warm_res = post("/warm/eu-west-3")
print("  Resposta:", warm_res)

# 2. Get active key
print("\n[Passo 2] Obter uma chave de cache ativa em 'eu-west-3'...")
plan = get("/plan")
first_event = plan["regions"]["eu-west-3"][0]
first_entry = first_event["entries"][0]
test_key = first_entry["cache_key"]
print(f"  Evento: {first_event['event_name']}")
print(f"  Chave selecionada: {test_key}")

# 3. Simulate 6 misses
print("\n[Passo 3] Simular apenas 6 falhas (misses) de tráfego com 0 acertos...")
for i in range(6):
    post("/simulate/miss", {"cache_key": test_key})
print("  -> 6 misses registados com sucesso!")

# 4. Run Self-Critic with min_requests=1
print("\n[Passo 4] Executar Auto-Crítica com limiar ágil (min_requests=1)...")
critique_run = post("/critique/run", {"min_requests": 1})
print("  Resultado:", json.dumps(critique_run, indent=2, ensure_ascii=False))

# 5. Fetch full report
print("\n[Passo 5] Inspecionar relatório completo (GET /critique)...")
critique = get("/critique")
print("  Overall Passed:", critique.get("overall_passed"))
print("  Feedback escrito para AI:", critique.get("feedback_written_to_ai"))
for c in critique.get("critiques", []):
    status_str = "OK" if c["passed"] else "FALHOU (Aviso gerado!)"
    print(f"  [{status_str}] [{c['region']}] {c['event_name']}")
    print(f"     Taxa de Hits Real: {c['actual_hit_rate']*100:.1f}% | Esperado: {c['expected_hit_rate']*100:.1f}%")
    print(f"     Recomendação: {c['recommendation'][:95]}...")

print("\n" + "=" * 60)
if critique.get("overall_passed") is False and critique.get("feedback_written_to_ai") is True:
    print("🎉 SUCESSO TOTAL! A falha foi detetada imediatamente e o feedback foi enviado para o AI!")
else:
    print("Aviso: verificar condições.")
print("=" * 60)
