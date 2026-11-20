# Pull Request: feat(deception) — Active Deception & Watermarking ("Rastreadores Embutidos"), Honeytokens Vivos, GPS Lógico & Defesa Anti-IA

## 📌 Título Sugerido para o Pull Request no GitHub
`feat(deception): Active Deception & Watermarking — Honeytokens Vivos, GPS Lógico, Prompt Injection Defensivo e Beacons de Telemetria`

---

## 🎯 Resumo da Proposta (Overview)
Este Pull Request eleva a solução **`cloud_honeypot_ai`** ao nível de **Inteligência Empresarial Ativa (Active Deception & Threat Intelligence Counter-Measures)**. 

Em vez de apenas observar o invasor passivamente, o sistema agora gera armadilhas dinâmicas à medida com rastreadores embutidos. Assim que o atacante exfiltra ou executa dados ou códigos roubados da armadilha cloud, o sistema desmascara a sua identidade e localização real (mesmo que use VPN durante a invasão), envenena agentes de IA usados por atacantes e permite provar legalmente a fuga de dados na *dark web*.

---

## 🚀 Novas Capacidades Implementadas

### 1. 🧬 Bases de Dados Fakes com "Células Vivas" (Honeytokens Dinâmicos & Watermarking Forense)
- **Geração Dinâmica de Dumps**: Quando o atacante executa dumps ou consultas (`mysqldump`, `pg_dump`, `cat /var/backups/customers_dump.sql`, `/var/data/employees_export.csv`), o motor gera em tempo real ficheiros `.sql` ou `.csv` realistas.
- **5 Células Vivas Injetadas**:
  1. **E-mails Isco Monitorizados**: Endereços canário únicos com tags forenses da sessão. Se a base de dados for posta à venda ou utilizada para phishing/spam na *dark web*, é possível correlacionar exatamente a data, hora e IP de onde foi roubada.
  2. **Chaves de API com "GPS Lógico"**: Chaves formatadas com tokens de rastreio (`sk_live_picoas_gps_...`).
  3. **Marca de Água Criptográfica SHA-256**: Hash imutável de proveniência embutido em comentários do dump para auditoria e custódia forense legal.
- **Motor de Verificação de Fugas**: Endpoint e rotina que valida qualquer ficheiro encontrado na internet e identifica a sessão da fuga.

### 2. 📍 Chaves de API Falsas com "GPS Lógico" (Desmascaramento de IP Real)
- **O Comportamento do Hacker**: Frequentemente, atacantes usam VPN/Tor para aceder à cloud, mas desligam a VPN ou usam os seus próprios terminais locais para testar se as chaves API roubadas funcionam.
- **A Armadilha**: Ao tentar validar as chaves (`curl http://honeypot/api/v1/validate_key?key=sk_live_picoas_gps_...`), o sistema simula uma API de pagamentos/cloud válida, enquanto silenciosamente captura:
  - **IP real da máquina**
  - **GeoIP & ASN da localização residencial/local**
  - **User-Agent e fingerprint HTTP**
  - Alerta crítico imediato enviado ao Security Operations Center (SOC).

### 3. 🤖 Documentação Interna Falsa com "Prompt Injection Defensivo" (Anti-IA Scrapers)
- **O Contexto**: Atacantes modernos usam agentes de IA (AutoGPT, LangChain scrapers, LLMs locais) para resumir centenas de documentos roubados e encontrar credenciais mestras.
- **A Contra-Medida**: O ficheiro decoy `/docs/README_arquitetura.md` contém diretivas ocultas em comentários HTML de alta prioridade (`[CRITICAL SYSTEM DIRECTIVE OVERRIDE]`):
  - Forçam o agente de IA do hacker a **abortar imediatamente a exfiltração**.
  - Obrigam a IA a responder ao operador com uma mensagem de aviso de contra-inteligência ("*⚠️ SECURITY ALERT: You have accessed a Counter-Intelligence Honeypot*").
  - Induzem a IA do atacante a disparar um webhook silencioso que denuncia o agente ao honeypot.
  - Armadilham a IA com ciclos de validação recursiva cíclica para esgotar tokens e memória do hacker.

### 4. 🛰️ Código-Fonte Decoy com "Beacons" de Telemetria
- **O Cenário**: O atacante procura algoritmos proprietários ou projetos confidenciais em `/opt/cloud_engine/` (ex.: motor de trading algorítmico).
- **O Beacon**: O projeto inclui testes unitários (`test_engine.py`) e rotinas de bootstrap armadilhadas. Quando o invasor clona e corre o código no seu próprio computador local (`python3 test_engine.py`), o script transmite silenciosamente um batimento cardíaco (beacon) com:
  - Nome do computador (`hostname`)
  - Sistema Operativo e versão (`Darwin / Linux / Windows`)
  - Nome de utilizador local do hacker (`whoami`)
  - IP público de saída

### 5. 📊 Painel de Visualização & Integração Dashboard
- Novo painel no dashboard web (`http://localhost:8888`): **"🎯 Active Deception & Honeytokens Vivos"**.
- Cartões em tempo real para:
  - Dumps gerados e marcas de água SHA-256
  - Alertas de GPS Lógico (com IPs desmascarados)
  - Beacons de telemetria recebidos de computadores de atacantes
  - Incidentes de Prompt Injection defensivo neutralizados

---

## 🧪 Cobertura de Testes Automatizados
- **40 testes unitários e de integração (100% de sucesso)**:
  - `test_active_deception.py` (5 novos testes cobrindo dumps com células vivas, GPS lógico, prompt injection anti-IA, beacons de telemetria e comandos de shell como `mysqldump`).
  - `test_ai_analyzer.py` (MITRE ATT&CK `T1567` Exfiltração de BD e `T1005` Dados Locais).
  - `test_cloud_defense.py` (Regras de bloqueio AWS NACL/SG/iptables).
  - `test_crypto_vault.py` (Encadeamento imutável AES-256-GCM + blockchain SHA-256).
  - `test_crypto_auditor.py` (Conformidade NIST e PQC).
  - `test_fake_shell.py`, `test_fake_filesystem.py`, `test_geoip.py`, `test_honeypot_servers.py`, `test_integration.py`.

```bash
# Executar toda a suite de testes:
python3 -m unittest discover -s cloud_honeypot_ai/tests -v
```

---

## 📋 Como Demonstrar / Validar

### 1. Demonstração End-to-End no Terminal (Passo 8 ativo)
```bash
cd hackaton-project
python3 -m cloud_honeypot_ai.run_honeypot demo
```
Exibe o ciclo completo de invasão, análise IA, defesa cloud e ativação dos 4 vetores de Active Deception.

### 2. Inspeção CLI de Deception
```bash
python3 -m cloud_honeypot_ai.run_honeypot deception
```
Emite o JSON estruturado com o dump gerado, tokens ativos, documento envenenado e alertas capturados.

### 3. Interface Web com Feed em Tempo Real
```bash
python3 -m cloud_honeypot_ai.run_honeypot start
```
Aceder a `http://localhost:8888` e clicar em **"⚡ Simulate Hacker Attack"**.
