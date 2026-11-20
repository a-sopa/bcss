import sys, json, pathlib
sys.path.insert(0, '.')

from models.prediction import PredictionFile
from models.cache_plan import WarmingStatus
from services.cache_planner import CachePlanner
from services.self_critic import SelfCritic

with open('data/predictions.json', encoding='utf-8') as f:
    data = json.load(f)

predictions = PredictionFile.from_raw_json(data)
planner = CachePlanner()
plan = planner.build_plan(predictions)

available_regions = list(plan.region_plans.keys())
assert len(available_regions) >= 1, "Plan must contain at least one region"

reg_a = available_regions[0]
reg_b = available_regions[1] if len(available_regions) > 1 else available_regions[0]

# Cenário A: reg_a com boa performance (80% hits)
plan_a = plan.region_plans[reg_a][0]
plan_a.status = WarmingStatus.HOT
for entry in plan_a.entries:
    entry.hit_count = 8
    entry.miss_count = 2

# Cenário B: reg_b com má performance (apenas 10 pedidos, 10% hit rate)
plan_b = plan.region_plans[reg_b][-1]
plan_b.status = WarmingStatus.HOT
for entry in plan_b.entries:
    entry.hit_count = 1
    entry.miss_count = 9

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

assert report.regions_failed >= 1, "Region with 10% hit rate must fail evaluation!"
assert report.feedback_written is True, "Feedback must be written when a region fails!"

fb = pathlib.Path('data/feedback.json')
if fb.exists():
    feedback = json.loads(fb.read_text(encoding='utf-8'))
    n = len(feedback['failed_regions'])
    instr = feedback['instruction_to_ai'][:90]
    print()
    print(f"feedback.json criado com {n} regiao(oes) com falha")
    print(f"Instrucao para o AI: {instr}")

print("\n✅ TESTE DE AUTOCRÍTICA PASSOU COM SUCESSO!")
