# 🛡️ Cloud Honeypot AI Shield ("A Armadilha para Hackers")

> **Hackathon Picoas 2026** — Solução de Cibersegurança, Eficiência em Cloud e Inteligência Artificial.

---

## 📌 1. Visão Geral do Projeto

### O Problema na Cloud
Existem milhares de robôs e botnets automatizados a varrer a internet diariamente, tentando adivinhar credenciais (ataques de *brute-force* e *dictionary attacks*) para invadir servidores cloud (AWS, Azure, GCP).
Além do risco crítico de invasão, estes ataques geram um **enorme problema de eficiência e custos na cloud**:
1. **Desperdício de CPU/Compute**: Servidores de produção gastam ciclos a processar negociações TLS e *hashes* criptográficos de passwords falhadas.
2. **Saturação de Rede**: Tráfego contínuo consome largura de banda (taxas de *egress/ingress*).
3. **Explosão de Custos de Monitorização**: Milhares de tentativas de login enchem os logs da cloud (como o AWS CloudWatch ou Datadog), aumentando as faturas em centenas de dólares.

---

## 🎯 2. A Solução: "A Armadilha para Hackers" (Honeypot) com IA e Criptografia

A metáfora: **Deixar uma bicicleta velha destrancada na rua com uma câmara apontada só para filmar como os ladrões atuam.**

Implementámos um servidor Honeypot leve que:
1. **Deixa a porta "meio aberta" de propósito**: Aceita credenciais fracas configuradas (ex.: `admin123`, `ubuntu`, `root`).
2. **Ambiente Simulado Confinado (Zero Perigo)**: O atacante entra num terminal Linux simulado em memória (`FakeShell` e `FakeFilesystem`). Não tem acesso a nada real do sistema anfitrião.
3. **Gravação Forense Total**: Grava o país de origem (GeoIP), ASN/ISP, passwords tentadas, comandos digitados e ferramentas/scripts que tentou descarregar (`wget`, `curl`).
4. **Inteligência Artificial (IA)**:
   - **Classificador Comportamental**: Distingue automaticamente *Botnets Automatizadas*, *Script Kiddies* e *Atacantes Humanos (APT)* analisando entropia e velocidade de execução.
   - **Mapeamento MITRE ATT&CK**: Mapeia todas as ações para a matriz oficial da cloud (T1110 Brute Force, T1059 Shell, T1082 Reconhecimento, T1105 Download de Malware, T1548 Elevação de Privilégios, T1552 Credenciais em Ficheiros).
   - **Score de Ameaça Dinâmico (0-100)** e Relatório Executivo de Inteligência.
5. **Otimização de Eficiência na Cloud (Defesa Ativa)**:
   - Gera regras de firewall automáticas para **AWS Network ACL (NACL)** (drop sem estado na borda da sub-rede antes de chegar ao EC2), **AWS Security Groups**, **Linux `iptables`** e **Cloudflare WAF**.
   - **Calculador de Poupança Cloud**: Quantifica GB de tráfego poupados, ciclos de CPU preservados e redução na fatura de log ingestion do CloudWatch.
6. **Módulo Criptográfico & Ligação ao JunctionX (QuantumTrace)**:
   - *Nota de conformidade*: O projeto original `JunctionX` foi mantido **100% inalterado**, criando este módulo independente com toda a sua utilidade.
   - **Forensic Crypto Vault (`crypto/vault.py`)**: Encriptação autenticada **AES-256-GCM**, encadeamento imutável de blocos com **SHA-256 (estilo blockchain)** e assinaturas **HMAC-SHA256**. Prova matematicamente que as evidências dos hackers não foram manipuladas ou apagadas.
   - **Auditor de Postura Criptográfica na Cloud (`crypto/posture_auditor.py`)**: Avalia a segurança dos algoritmos SSH, TLS e chaves AWS KMS, identificando algoritmos obsoletos (3DES, SHA-1, MD5, CBC) e pontuando a preparação para Criptografia Pós-Quântica (**PQC / NIST FIPS 203 ML-KEM**).
   - **Honey-Tokens Criptográficos (`crypto/canary_keys.py`)**: Chaves RSA e credenciais AWS KMS canário espalhadas no sistema para apanhar exfiltrações em flagrante.

---

## 🏗️ 3. Estrutura do Código

```
hackaton-project/
├── JunctionX/                         # [INTACTO] Projeto anterior de criptografia
└── cloud_honeypot_ai/                 # Nova Solução de Honeypot, IA e Cloud Defense
    ├── config.py                      # Portas, passwords fracas, ambiente simulado
    ├── run_honeypot.py                # CLI principal unificado
    ├── requirements.txt               # Dependências Python (cryptography)
    ├── core/                          # Núcleo da Armadilha
    │   ├── geoip.py                   # Resolução de GeoIP/ASN com fallback offline
    │   ├── session.py                 # Registo forense de sessões e tentativas
    │   ├── fake_filesystem.py         # Sistema de ficheiros Linux com canários (~/.aws, .env)
    │   ├── fake_shell.py              # Interpretador bash (whoami, uname, cat, curl, etc.)
    │   ├── tcp_honeypot.py            # Servidor TCP / Telnet interativo
    │   ├── ssh_honeypot.py            # Servidor SSH com negociação de banner
    │   ├── http_honeypot.py           # Trap HTTP (.env, IMDS AWS SSRF, admin portal)
    │   └── honeypot_manager.py        # Gestor dos listeners
    ├── ai/                            # Motor de Inteligência Artificial & Eficiência
    │   ├── bot_classifier.py          # Classificação Bot vs Humano (ML & heurísticas)
    │   ├── mitre_attack.py            # Mapeamento oficial MITRE ATT&CK
    │   ├── threat_analyzer.py         # Cálculo de Risk Score & Relatório de Ameaça
    │   └── cloud_defense.py           # Geração de regras AWS NACL/SG/iptables & ROI
    ├── crypto/                        # Módulo Criptográfico (Utilidade JunctionX)
    │   ├── vault.py                   # Cofre Forense (AES-256-GCM + SHA-256 + HMAC)
    │   ├── posture_auditor.py         # Auditor de Cifras, TLS, KMS e PQC NIST
    │   └── canary_keys.py             # Gerador de chaves RSA e credenciais isco
    ├── web/                           # Dashboard Visual
    │   ├── app.py                     # Servidor HTTP do dashboard
    │   └── static/                    # Interface dark-mode com feed ao vivo e terminal
    └── tests/                         # Suite de Testes Automatizados (35 testes, 100% pass)
        ├── test_geoip.py
        ├── test_fake_filesystem.py
        ├── test_fake_shell.py
        ├── test_honeypot_servers.py
        ├── test_ai_analyzer.py
        ├── test_cloud_defense.py
        ├── test_crypto_vault.py
        ├── test_crypto_auditor.py
        └── test_integration.py
```

---

## ⚡ 4. Como Executar e Demonstrar

### A. Executar a Demonstração Completa (End-to-End)
Executa em segundos uma simulação completa: conexão de atacante externo, ataque de dicionário, entrada no terminal isco com credencial `admin123`, execução de comandos maliciosos, roubo de canários AWS, análise por IA, selagem criptográfica no cofre e cálculo de poupança na cloud:

```bash
cd hackaton-project
python3 -m cloud_honeypot_ai.run_honeypot demo
```

### B. Iniciar os Serviços e o Dashboard Web
Inicia todos os decoys de rede (SSH, Telnet, HTTP) e o dashboard visual:

```bash
cd hackaton-project
python3 -m cloud_honeypot_ai.run_honeypot start
```
- **Dashboard Web**: Abra o browser em `http://localhost:8888`
- **Simular Conexão TCP/Telnet**: `nc localhost 2323` (digite user `ubuntu` e password `admin123`)
- **Simular Ataque HTTP**: `curl http://localhost:8080/.env`
- **Verificar Banner SSH**: `nc localhost 2222` ou `ssh -p 2222 root@localhost`

### C. Executar a Suite de Testes (100% Automatizada)
Corre todos os 35 testes unitários e de integração:

```bash
cd hackaton-project
python3 -m unittest discover -s cloud_honeypot_ai/tests -v
```

### D. Outros Comandos Úteis do CLI

```bash
# Gerar regras de firewall para a Cloud (AWS NACL, Security Groups, iptables)
python3 -m cloud_honeypot_ai.run_honeypot defend

# Executar Auditoria de Postura Criptográfica na Cloud (estilo JunctionX)
python3 -m cloud_honeypot_ai.run_honeypot crypto-audit

# Verificar Integridade Criptográfica do Cofre Forense
python3 -m cloud_honeypot_ai.run_honeypot vault-verify
```
