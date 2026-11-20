import sys, json, pathlib
sys.path.insert(0, '.')

from models.prediction import PredictionFile
from models.cache_plan import WarmingStatus
from services.cache_planner import CachePlanner
from services.self_critic import SelfCritic

with open('data/predictions.json') as f:
    data = json.load(f)

predictions = PredictionFile.model_validate(data)
planner = CachePlanner()
plan = planner.build_plan(predictions)

# Cenário A: eu-west-1 (Benfica) com boa performance (80% hits)
eu_plan = plan.region_plans['eu-west-1'][0]
eu_plan.status = WarmingStatus.HOT
for entry in eu_plan.entries:
    entry.hit_count = 80
    entry.miss_count = 20

# Cenário B: us-east-1 (US News) com má performance (20% hits)
us_plan = plan.region_plans['us-east-1'][0]
us_plan.status = WarmingStatus.HOT
for entry in us_plan.entries:
    entry.hit_count = 20
    entry.miss_count = 80

critic = SelfCritic()
report = critic.evaluate(plan)

print("Avaliacao concluida:")
print(f"  Regioes avaliadas: {report.regions_evaluated}")
print(f"  Regioes com falha: {report.regions_failed}")
print(f"  Overall passou: {report.overall_passed}")
print(f"  Feedback escrito para AI: {report.feedback_written}")
print()
for c in report.critiques:
    status = "OK" if c.passed else "FALHOU"
    print(f"  [{status}] [{c.region}] {c.event_name}")
    print(f"     Hit rate real: {c.overall_hit_rate:.1%} | Esperado: {c.expected_hit_rate:.1%}")
    print(f"     Recomendacao: {c.recommendation[:90]}")

fb = pathlib.Path('data/feedback.json')
if fb.exists():
    feedback = json.loads(fb.read_text())
    n = len(feedback['failed_regions'])
    instr = feedback['instruction_to_ai'][:90]
    print()
    print(f"feedback.json criado com {n} regiao(oes) com falha")
    print(f"Instrucao para o AI: {instr}")
