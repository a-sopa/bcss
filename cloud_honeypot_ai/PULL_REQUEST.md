# Pull Request: feat(honeypot) — AI-Powered Cloud Honeypot, Adaptive Defense & Forensic Cryptographic Evidence Vault

## 📌 Sugestão de Título do Pull Request
`feat(honeypot): AI Cloud Honeypot Shield ("A Armadilha para Hackers"), Adaptive Cloud Defense & Forensic Cryptographic Vault`

---

## 🎯 Resumo da Proposta (Overview)
Este Pull Request introduz o módulo **`cloud_honeypot_ai`** ("A Armadilha para Hackers"), focado em resolver os desafios de **Segurança** e **Eficiência de Custos e Recursos em Cloud** utilizando **Inteligência Artificial** e **Criptografia Avançada**.

A solução baseia-se no princípio: *Deixar uma bicicleta velha destrancada na rua com uma câmara apontada só para filmar e entender como os ladrões atuam.*

Alocando um ambiente decoy leve na internet com a porta "meio aberta" (passwords fracas conhecidas como `admin123`), os robôs e atacantes entram num sandbox inofensivo em memória, enquanto o sistema grava toda a atividade, classifica o comportamento com IA, gera regras automáticas de firewall para proteger a cloud real e sela as evidências num cofre criptográfico imutável.

---

## 🚀 Principais Capacidades Implementadas

### 1. 🪤 Multi-Protocol Decoy & Confinement Seguro
- **Fake SSH / Telnet / HTTP Decoys**: Portas de escuta configuráveis para captura de ataques de dicionário e *brute-force*.
- **FakeShell & FakeFilesystem**: Terminal bash simulado em memória com suporte a comandos reais (`whoami`, `uname -a`, `id`, `cat`, `curl`, `wget`, `sudo su`, `ifconfig`, `ps`). **Zero perigo para o host real**.
- **Honey-Tokens Canário**: Ficheiros isco (`~/.aws/credentials`, `/app/.env`, `/etc/shadow`) que disparam alertas imediatos caso o atacante tente exfiltrar credenciais da cloud.

### 2. 🧠 Inteligência Artificial Comportamental & MITRE ATT&CK
- **Bot vs Human Classifier**: Algoritmo de análise de velocidade de execução e entropia de comandos para categorizar o invasor (`AUTOMATED_BOTNET`, `SCRIPT_KIDDIE`, `TARGETED_APT`).
- **Mapeamento MITRE ATT&CK**: Mapeamento em tempo real para matriz de Linux/Cloud:
  - `T1110.001` (Password Guessing / Brute Force)
  - `T1552.001` (Credentials in Files)
  - `T1082` (System Information Discovery)
  - `T1105` (Ingress Tool Transfer - curl/wget)
  - `T1548.003` (Sudo Privilege Escalation)
  - `T1496` (Resource Hijacking / Cryptomining)
- **Threat Scoring (0 a 100)** e geração de **Relatórios Executivos de Inteligência** em linguagem natural.

### 3. ⚡ Otimização de Eficiência e Redução de Custos na Cloud
- **O Problema**: Milhões de pedidos de botnets gastam computação (vCPU), largura de banda de rede e inflam as faturas de ingestão de logs do AWS CloudWatch e Datadog.
- **A Solução de Defesa Automática**:
  - Geração automática de regras **AWS Network ACL (NACL)** (descarte *stateless* na borda da sub-rede antes de atingir os nós EC2).
  - Regras de **AWS Security Groups**, **Linux `iptables` / `nftables`** e **Cloudflare WAF**.
  - **Calculadora de ROI Cloud**: Quantifica GB de tráfego poupados, ciclos de CPU preservados e poupança mensal direta na fatura cloud.

### 4. 🔐 Módulo Criptográfico Forense (Inspirado no JunctionX)
- Mantém o **JunctionX 100% inalterado**, complementando-o com:
  - **Forensic Crypto Vault (`crypto/vault.py`)**: Encriptação autenticada **AES-256-GCM** com nonces de 96 bits, encadeamento de blocos em **SHA-256 (estilo blockchain)** e assinaturas **HMAC-SHA256**. Impede qualquer adulteração ou eliminação de provas por parte do atacante.
  - **Cloud Cryptographic Posture Auditor (`crypto/posture_auditor.py`)**: Auditoria de cifras fracas (3DES, CBC, MD5, SHA-1), avaliação de conformidade NIST SP 800-131A e cálculo de prontidão para Criptografia Pós-Quântica (**PQC / NIST FIPS 203 ML-KEM**).

### 5. 🖥️ Dashboard Web Interativo
- Servidor web leve embutido (`http://localhost:8888`) com interface moderna *dark-mode*:
  - Métricas em tempo real de sessões, países de origem e poupança em dólares.
  - Tabela com histórico de ataques e passwords tentadas.
  - Replay visual do terminal do atacante.
  - Botão interativo **"⚡ Simulate Hacker Attack"** para demonstrações instantâneas aos júris.

---

## 🧪 Validação e Testes
Todos os componentes contam com cobertura de testes unitários e de integração:
- **35 testes executados**: 100% de sucesso (`Ran 35 tests in 5.8s - OK`).
- Validação de integridade do cofre forense e deteção de adulteração de blocos testada.
- Resolução e fallback de GeoIP testados.
- Execução isolada na sandbox verificada.

---

## 📋 Como Testar
```bash
# 1. Executar Demonstração Completa
python3 -m cloud_honeypot_ai.run_honeypot demo

# 2. Iniciar Honeypot e Dashboard
python3 -m cloud_honeypot_ai.run_honeypot start

# 3. Rodar Testes Automatizados
python3 -m unittest discover -s cloud_honeypot_ai/tests -v
```
