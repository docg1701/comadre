# Comadre vs TTS na Nuvem: Comparativo de Custo e Desempenho

## Resumo Executivo

O Comadre entrega audio TTS ilimitado por um custo fixo de $7/mes em um unico VPS (ou custo quase zero em hardware proprio), com vazao medida de 18 mensagens de audio por minuto, 100% de integridade de audio em 818 requisicoes de teste e latencia previsivel sob carga. A qualidade de voz e muito boa — comparavel ao MiniMax, superior ao Microsoft Edge TTS e apenas ligeiramente inferior aos melhores modelos da ElevenLabs. O projeto complementar kokoro-cloner permite criar vozes personalizadas a partir de uma amostra de 10 segundos. Para um negocio que atende 120 clientes/dia em portugues brasileiro, o Comadre custa 97-99% menos que a ElevenLabs e 35-77% menos que o AI33.pro, oferecendo privacidade total dos dados, conformidade com a LGPD por design e zero dependencias externas. A contrapartida e a necessidade de gerenciar a propria infraestrutura e um catalogo de vozes menor em comparacao com a ElevenLabs.

Todos os numeros de desempenho do Comadre neste relatorio foram medidos usando exclusivamente o **motor Kokoro** (inferencia em CPU, sem GPU). O Comadre tambem suporta Qwen3-TTS para clonagem de voz, mas o Qwen3 tem latencia significativamente maior em CPU e nao e adequado para producao com alto volume. Todas as comparacoes de vazao, latencia e custo neste relatorio refletem exclusivamente o desempenho do Kokoro. Os custos das plataformas na nuvem sao calculados a partir dos precos publicados.

## Perfil das Plataformas

### Comadre (Self-Hosted)

API TTS de codigo aberto com dois motores, otimizada para portugues brasileiro. Roda em um VPS padrao sem necessidade de GPU.

- **Motor principal:** Kokoro fp32 — inferencia rapida em CPU, sem GPU. Todos os benchmarks deste relatorio usam o Kokoro.
- **Motor secundario:** Qwen3-TTS C++ Q8_0 — capacidade de clonagem de voz, mas latencia alta em CPU (nao usado nos benchmarks)
- **Deploy:** Docker Compose em qualquer VPS (minimo 4 vCPU, 8 GB RAM)
- **Modelo de preco:** Custo fixo mensal de VPS (Hetzner CX33: EUR 6,49/mes = ~$7,01/mes) ou custo quase zero em hardware proprio
- **API:** Compativel com OpenAI (`POST /v1/audio/speech`)
- **Idiomas:** Otimizado para portugues brasileiro (dicionario personalizado espeak-ng, 67 siglas cadastradas)

### ElevenLabs (Cloud SaaS)

Lider do mercado em TTS na nuvem, com qualidade de voz premium e extensa biblioteca de vozes.

- **Modelo de preco:** Assinatura escalonada + excedente por caractere

| Plano | Preco/mes | Caracteres | Minutos de audio | Custo/min |
|-------|-----------|-----------|------------------|-----------|
| Starter | $5 | 30.000 | ~30 | $0,167 |
| Creator | $22 | 100.000 | ~100 | $0,220 |
| Pro | $99 | 500.000 | ~500 | $0,198 |
| Scale | $330 | 2.000.000 | ~2.000 | $0,165 |
| Excedente (Scale) | -- | -- | -- | $0,180/1k chars |

*~1.000 caracteres = 1 minuto de audio (documentacao ElevenLabs).*

### AI33.pro (Cloud API)

Agregador de TTS na nuvem que revende acesso a multiplos provedores — ElevenLabs, MiniMax e Microsoft Edge TTS — atraves de um sistema unificado de creditos.

- **Provedores:** ElevenLabs (vozes premium), MiniMax (multilingual), Microsoft Edge TTS (qualidade basica)
- **Qualidade de voz:** Varia por provedor — vozes ElevenLabs sao excelentes, MiniMax e muito bom, Edge e aceitavel
- **Clonagem de voz:** Sim (via provedor ElevenLabs)
- **Idiomas:** Dezenas (herda do suporte multilingual da ElevenLabs + MiniMax)
- **Modelo de preco:** Pacotes de creditos
- **Taxa:** $10 por 2.100.000 creditos
- **Custo por audio (12s):** Edge ~90 creditos, ElevenLabs/MiniMax ~140-190 creditos
- **Taxa efetiva (ElevenLabs/MiniMax):** ~12.350 audios por $10 = $0,00081/audio
- **Taxa efetiva (Edge):** ~23.330 audios por $10 = $0,00043/audio
- **Custo por minuto de audio:** $0,0041 (ElevenLabs/MiniMax), $0,0021 (Edge)
- **Contrapartida:** A qualidade depende do provedor. Edge e o mais barato, mas inferior ao Kokoro (sem clonagem, prosodia pior). ElevenLabs e a melhor qualidade, mas custa 2x mais creditos. Para igualar a qualidade do Comadre, e necessario usar o tier MiniMax/ElevenLabs — nao o tier barato do Edge. Latencia e disponibilidade dependem dos provedores upstream.

## Desempenho Medido (Comadre — Motor Kokoro)

Todos os dados foram obtidos em testes de carga realizados em 06/04/2026 contra uma VM Proxmox self-hosted (4 vCPU, 8 GB RAM, Xeon E5-2680v4). A configuracao de hardware e comparavel a um VPS Hetzner CX33 (4 vCPU compartilhados, 8 GB RAM, EUR 6,49/mes) — usado como referencia de custo ao longo deste relatorio.

### Vazao

| Teste | Requisicoes | Taxa de sucesso | Vazao | Integridade de audio |
|-------|-------------|-----------------|-------|---------------------|
| Teste de saturacao | 208 | 97,1% (timeouts com 50 simultaneas) | 10,9 req/min | 208/208 (100%) |
| Teste de capacidade | 610 | 100% (sem timeout, espera ilimitada) | 18,0 req/min max | 610/610 (100%) |
| **Combinado** | **818** | -- | -- | **818/818 (100%)** |

### Latencia por Taxa de Requisicoes

Medido com mensagens de audio de 5-12 segundos (80-200 caracteres, mensagens tipicas de chatbot):

| Taxa alvo | Vazao real | Latencia p50 | Latencia p95 | Latencia max | Profundidade da fila |
|-----------|-----------|-------------|-------------|-------------|---------------------|
| 2/min | 2,1/min | 3,0s | 5,0s | 5,5s | 1 |
| 5/min | 5,2/min | 2,9s | 5,0s | 5,5s | 1 |
| 10/min | 10,2/min | 2,9s | 5,1s | 5,5s | 1 |
| 20/min | 18,0/min | 11,3s | 18,5s | 20,2s | 6 |
| 30/min | 18,0/min | 36,4s | 72,6s | 81,5s | 25 |
| 50/min | 18,2/min | 106,5s | 204,7s | 211,7s | 65 |

### Latencia por Tamanho do Texto (Requisicao Unica, Sem Fila)

| Tamanho | Caracteres | Duracao do audio | Tempo de geracao |
|---------|-----------|-----------------|-----------------|
| Curto | ~50 | 2,5-3,2s | 1,4-1,7s |
| Medio | ~200 | 11,4-13,0s | 5,2-6,1s |
| Longo | ~450 | 26,5-27,4s | 11,6-12,3s |

### Uso de Recursos

| Metrica | Valor |
|---------|-------|
| Memoria em repouso | ~574 MB |
| Memoria sob carga | ~1.490 MB (estavel) |
| Pico de memoria (todos os testes) | 1.497 MB |
| Vazamento de memoria | Nenhum detectado |
| Limite de CPU | 4 nucleos (100% durante geracao) |
| Crashes durante testes | 0 |
| Corrupcao de audio | 0/818 |

## Comparativo de Custos

### Premissas

- **Dias uteis:** 22 por mes
- **Horas de trabalho:** 8 por dia
- **Mensagens por cliente:** 6 (conversa tipica de vendas/pos-venda)
- **Distribuicao de pico:** 60% do trafego em 4 horas de pico (10-12h, 14-16h)
- **Referencia de custo Comadre:** Hetzner CX33 a EUR 6,49/mes ($7,01/mes) — configuracao comparavel ao ambiente de teste self-hosted. Custo self-hosted e quase zero (apenas eletricidade).

### Cenario A: Mensagens de Audio Curtas (media 7 segundos, ~100 chars)

| Porte | Clientes/dia | Msgs/dia | Msgs/mes | Audio min/mes | Comadre | ElevenLabs | AI33.pro |
|-------|-------------|----------|----------|--------------|---------|------------|----------|
| Micro | 50 | 300 | 6.600 | 770 | **$7** | $330 (Scale) | $5,34 |
| Pequeno | 120 | 720 | 15.840 | 1.848 | **$7** | $330 (Scale) | $12,82 |
| Medio | 300 | 1.800 | 39.600 | 4.620 | **$7** | $802 (Scale+) | $32,05 |
| Em crescimento | 500 | 3.000 | 66.000 | 7.700 | **$14** (2x VPS) | $1.218 (Scale+) | $53,41 |
| Grande | 1.000 | 6.000 | 132.000 | 15.400 | **$21** (3x VPS) | $2.304 (Scale+) | $106,82 |

### Cenario B: Mensagens de Audio Longas (media 17,5 segundos, ~200 chars)

| Porte | Clientes/dia | Msgs/dia | Msgs/mes | Audio min/mes | Comadre | ElevenLabs | AI33.pro |
|-------|-------------|----------|----------|--------------|---------|------------|----------|
| Micro | 50 | 300 | 6.600 | 1.925 | **$7** | $330 (Scale) | $7,79 |
| Pequeno | 120 | 720 | 15.840 | 4.620 | **$7** | $802 (Scale+) | $18,69 |
| Medio | 300 | 1.800 | 39.600 | 11.550 | **$14** (2x VPS) | $1.764 (Scale+) | $46,73 |
| Em crescimento | 500 | 3.000 | 66.000 | 19.250 | **$21** (3x VPS) | $2.844 (Scale+) | $77,88 |
| Grande | 1.000 | 6.000 | 132.000 | 38.500 | **$35** (5x VPS) | $5.556 (Scale+) | $155,76 |

### Custo por Minuto de Audio

| Plataforma | Custo/min (em escala) | Modelo |
|------------|----------------------|--------|
| **Comadre** | **$0,0004** (com 15.840 msgs/mes) | Fixo |
| AI33.pro | $0,0041 | Por credito |
| ElevenLabs | $0,165-0,220 | Por caractere |

O Comadre e **10x mais barato** que o AI33.pro e **400x mais barato** que a ElevenLabs por minuto de audio em volume tipico.

## Planejamento de Capacidade

O Comadre processa requisicoes sequencialmente (fila FIFO unica por instancia). Vazao por VPS:

| Duracao do audio | Vazao/VPS | Taxa maxima sustentavel |
|-----------------|-----------|------------------------|
| Curto (7s) | 18 req/min | 10 req/min (sem fila) |
| Longo (17,5s) | 10 req/min | 5 req/min (sem fila) |

### Quando Adicionar Instancias

Para chatbots WhatsApp, tempos de resposta de ate 120 segundos sao aceitaveis.

| Porte | Pico req/min | VPS necessarios (audio curto) | VPS necessarios (audio longo) | Custo mensal |
|-------|-------------|-------------------------------|-------------------------------|-------------|
| 50 clientes/dia | 3 | 1 | 1 | $7 |
| 120 clientes/dia | 5 | 1 | 1 | $7 |
| 300 clientes/dia | 12 | 1 | 2 | $7-14 |
| 500 clientes/dia | 20 | 2 | 3 | $14-21 |
| 1.000 clientes/dia | 40 | 3 | 5 | $21-35 |

A escalabilidade horizontal e feita adicionando instancias VPS atras de um balanceador de carga Caddy. Cada instancia e independente — sem estado compartilhado, sem overhead de coordenacao.

### Opcao de Hardware Proprio

Para empresas que possuem ou podem adquirir hardware, o Comadre roda em especificacoes minimas (CPU 4 nucleos, 4 GB RAM, qualquer maquina x86_64). A compra unica de hardware (~$150-300 para um mini PC ou desktop reaproveitado) elimina o custo mensal de VPS. O unico custo recorrente e a eletricidade (~R$15-25/mes para um mini PC de baixo consumo).

| Implantacao | Custo mensal | Total 1 ano | Total 2 anos |
|-------------|-------------|-------------|-------------|
| VPS Hetzner | $7/mes | $84 | $168 |
| Mini PC proprio | ~$3/mes (eletricidade) | ~$186 (hw + energia) | ~$222 |
| Hardware existente | ~$3/mes (eletricidade) | $36 | $72 |

O hardware proprio se paga em relacao ao VPS em ~12 meses se comprar hardware novo, ou e imediatamente mais barato se usar hardware existente.

## Latencia e Confiabilidade

### Comadre: Previsivel e Autocontrolado

Todos os numeros abaixo foram medidos:

| Condicao | Tempo de resposta | Fonte |
|----------|------------------|-------|
| Sem fila (< 10 req/min) | 3-6 segundos | Teste de capacidade |
| Fila leve (20 req/min) | 11 segundos p50 | Teste de capacidade |
| Fila pesada (30 req/min) | 36 segundos p50, 82s max | Teste de capacidade |
| Saturado (50 req/min) | 107 segundos p50 | Teste de capacidade |
| Crash do servidor | 0 incidentes em 818 requisicoes | Todos os testes |
| Corrupcao de audio | 0 incidentes em 818 requisicoes | Todos os testes |

A latencia do Comadre e deterministica: depende apenas da profundidade da fila, que depende apenas do seu proprio trafego. Nenhum outro cliente afeta o seu desempenho.

### Plataformas na Nuvem: Compartilhadas e Imprevisiveis

ElevenLabs e AI33.pro rodam em infraestrutura compartilhada. A latencia depende de:

- Carga total de todos os clientes no mundo
- Horario do dia (horario comercial em multiplos fusos)
- Picos sazonais (Black Friday, campanhas de fim de ano)
- Incidentes e manutencoes da plataforma
- Politicas de rate limiting que podem mudar sem aviso

Nenhuma das plataformas publica garantias de SLA para tempo de resposta. Uma requisicao que leva 2 segundos as 3h da manha pode levar 30 segundos as 10h de uma segunda-feira.

**O Comadre elimina essa incerteza.** Voce e dono da infraestrutura, mediu os limites e nenhum fator externo pode degradar o seu servico.

## Comparativo de Funcionalidades

| Funcionalidade | Comadre | ElevenLabs | AI33.pro |
|---------------|---------|------------|----------|
| **Qualidade de voz** | Muito boa (Kokoro) | Excelente | Varia (ElevenLabs/MiniMax/Edge) |
| **Otimizacao pt-BR** | Sim (dicionario personalizado) | Multilingual generico | Generico (via provedores) |
| **Pronuncia de siglas** | Perfeita (67 entradas verificadas) | Inconsistente | Inconsistente (sem dicionario) |
| **Clonagem de voz** | Sim (Qwen3 + kokoro-cloner) | Sim (premium) | Sim (via provedor ElevenLabs) |
| **Voicepacks personalizados** | Sim (pipeline kokoro-cloner) | Nao (clones predefinidos) | Nao |
| **Vozes pt-BR incluidas** | 3 otimizadas + ilimitadas via kokoro-cloner | Centenas (multilingual) | Centenas (de 3 provedores) |
| **Foco de idioma** | Apenas portugues brasileiro | Dezenas de idiomas | Dezenas (via ElevenLabs + MiniMax) |
| **Privacidade de dados** | Total (on-premise) | Nuvem (terceiros) | Nuvem (terceiros) |
| **Conformidade LGPD** | Inerente (dados nao saem do servidor) | Requer DPA | Requer DPA |
| **Controle de uptime** | Voce controla | Depende do fornecedor | Depende do fornecedor |
| **Dependencia de rede** | Nenhuma (funciona offline) | Requer internet | Requer internet |
| **Compatibilidade de API** | Compativel com OpenAI | Proprietaria | Proprietaria |
| **Previsibilidade de latencia** | Medida, deterministica | Variavel, compartilhada | Variavel, compartilhada |
| **Modelo de custo** | Mensal fixo | Por caractere | Por credito |
| **Custo com 15k msgs/mes** | $7/mes | $330/mes | $13/mes |
| **Escalabilidade horizontal** | Manual (adicionar VPS) | Automatica | Automatica |
| **Complexidade de setup** | Media (Docker + Ansible) | Nenhuma (SaaS) | Baixa (API key) |
| **Manutencao** | Autogerenciada | Zero | Zero |

## Qualidade de Voz e Clonagem

### Posicionamento de Qualidade

O motor Kokoro do Comadre produz audio de qualidade muito boa — comparavel ao MiniMax e visivelmente superior ao Microsoft Edge TTS. E apenas ligeiramente inferior aos modelos top de linha da ElevenLabs. A qualidade do AI33.pro varia conforme o provedor selecionado: as vozes ElevenLabs sao excelentes, as vozes MiniMax sao muito boas (comparaveis ao Comadre) e as vozes Edge sao de qualidade visivelmente inferior. Para mensagens de voz no WhatsApp, Telegram e Messenger, a diferenca de qualidade entre o Comadre e o tier MiniMax do AI33.pro e insignificante. A ElevenLabs mantem vantagem em casos de uso premium como audiobooks, vozes de marca e videos de marketing.

### Clonagem de Voz Personalizada com kokoro-cloner

O projeto complementar [kokoro-cloner](https://github.com/docg1701/kokoro-cloner) cria voicepacks Kokoro personalizados a partir de uma amostra de voz de 10 segundos. O pipeline:

1. **Amplify** — Chatterbox clona sua voz em 1.000 frases longas em pt-BR (5.000 WAVs de treinamento)
2. **Optimize** — Loss de speaker embedding ECAPA-TDNN atraves do Kokoro congelado retropropaga um vetor de estilo de 256 dimensoes para corresponder a sua voz
3. **Infer** — Kokoro gera fala com seu voicepack personalizado na velocidade nativa do Kokoro

O resultado e uma voz personalizada que roda na velocidade nativa do Kokoro (3-6 segundos por mensagem) sem penalidade de qualidade. Isso da ao Comadre o melhor dos dois mundos: identidade de voz personalizada com a menor latencia e custo.

Embora o Comadre venha com 3 vozes otimizadas para pt-BR, o kokoro-cloner permite **vozes personalizadas ilimitadas** — cada uma criada a partir de uma amostra de 10 segundos. O processo de clonagem roda uma unica vez, e o voicepack `.npy` resultante e colocado no diretorio `/voices/kokoro/` do Comadre — disponivel imediatamente, sem necessidade de reiniciar. Cada voz clonada herda a velocidade de inferencia rapida e o baixo uso de recursos do Kokoro.

**Tempo de clonagem por hardware:**

| GPU | VRAM | Tempo estimado | Observacoes |
|-----|------|---------------|-------------|
| RTX 2060 Super | 8 GB | ~6 horas | Medido. Gradient checkpointing ativado (limite de 8 GB) |
| RX 9060 XT | 16 GB | ~2-3 horas | Estimado. ~3x mais compute (RDNA 4), sem gradient checkpointing (16 GB) |
| Apenas CPU | 8 GB RAM | ~24-48 horas | Nao requer GPU, apenas mais lento |

A criacao de voz e um custo unico por voz. Uma vez gerado o voicepack, ele roda na velocidade nativa de inferencia do Kokoro indefinidamente.

## Contrapartidas Honestas: Onde o Comadre Perde

### Catalogo de Vozes

O Comadre vem com 3 vozes otimizadas para pt-BR prontas para uso. Novas vozes sao criadas pelo pipeline kokoro-cloner a partir de uma amostra de 10 segundos (~6 horas em uma RTX 2060 Super, ~2-3 horas em uma RX 9060 XT). A ElevenLabs oferece centenas de vozes prontas para uso em dezenas de idiomas — escolha uma do catalogo instantaneamente, sem pipeline. Para equipes que precisam de muitas vozes distintas rapidamente, a ElevenLabs tem uma vantagem pratica.

### Setup e Manutencao

Plataformas na nuvem nao exigem gerenciamento de infraestrutura. O Comadre requer provisionar um VPS, rodar playbooks Ansible e ocasionalmente atualizar o servico. Para equipes sem experiencia em DevOps, isso e uma barreira real. A automacao via Ansible reduz a operacao a poucos comandos, mas nao e zero.

### Escalabilidade Automatica

Plataformas na nuvem escalam de forma transparente. O Comadre requer adicionar instancias VPS manualmente e configurar um balanceador de carga. Para negocios com picos de trafego altamente imprevisiveis, esse processo manual adiciona overhead operacional.

### Apenas Portugues

O Comadre foi construido exclusivamente para portugues brasileiro — o preprocessamento de texto, o dicionario de siglas e o pos-processamento de audio sao todos especificos para pt-BR. Nao suporta outros idiomas. Se voce precisa de TTS multilingual, a ElevenLabs e a unica opcao viavel entre as tres plataformas comparadas aqui.

## Quando Escolher Cada Plataforma

### Escolha o Comadre Quando

- **Volume excede 300 mensagens/mes** — ponto de equilibrio vs ElevenLabs Starter
- **Privacidade de dados importa** — conversas de clientes nunca saem do seu servidor (LGPD)
- **Custos previsiveis sao essenciais** — $7/mes fixos independente do volume
- **Portugues brasileiro e o idioma principal** — dicionario de siglas personalizado, pronuncia testada
- **Voce precisa de latencia previsivel** — medida, autocontrolada, sem infraestrutura compartilhada
- **Voce quer uma voz de marca personalizada** — kokoro-cloner cria um voicepack a partir de uma amostra de 10 segundos
- **Voce tem capacidade basica de DevOps** — ou disposicao para aprender Docker + Ansible
- **Voce pode usar hardware proprio** — hardware existente elimina custos mensais por completo

### Escolha a ElevenLabs Quando

- **Qualidade de voz top e inegociavel** — audiobooks, narracao de video premium
- **Voce precisa de muitos idiomas** — audiencia global, suporte multilingual
- **Volume e inferior a 300 mensagens/mes** — plano Starter de $5/mes e dificil de bater
- **Zero gerenciamento de infraestrutura** — sem VPS, sem Docker, sem Ansible
- **Voce precisa de clonagem de voz instantanea** — sem pipeline, clone pela interface

### Escolha o AI33.pro Quando

- **Orcamento e a principal restricao** — menor custo por audio em volume baixo
- **Volume e inferior a 8.000 mensagens/mes** — abaixo disso, AI33 se aproxima do custo do Comadre
- **Voce aceita riscos de infraestrutura compartilhada** — latencia descontrolada, sem SLA
- **Simplicidade de setup importa mais que controle** — API key e pronto

## Apendice: Metodologia dos Testes

### Teste de Saturacao (`scripts/loadtest.py`)

- 6 cenarios: baseline, leve (3 simultaneas), moderado (10), pesado (20), stress (50), rajada (30 simultaneas)
- 208 requisicoes totais em todos os cenarios
- Validacao de audio via ffprobe (duracao > 0,1s)
- Monitoramento de saude a cada 1 segundo (profundidade da fila, memoria)
- Timeout: 130 segundos por requisicao

### Teste de Capacidade (`scripts/capacity_test.py`)

- 8 niveis de taxa: 2, 5, 10, 20, 30, 50, 75, 100 requisicoes/minuto
- 610 requisicoes totais em todos os niveis
- Sem timeout — cada requisicao esperou ate ser completada
- Corpus de texto: 12 frases em portugues brasileiro, 80-200 caracteres (produzindo audio de 5-12 segundos)
- Validacao de audio via ffprobe
- Monitoramento de saude a cada 1 segundo

### Ambiente

- **Host:** VM Proxmox 9.1.7 com Xeon E5-2680v4 (self-hosted, equivalente a um VPS de 4 vCPU)
- **Specs da VM:** 4 vCPU, 8 GB RAM
- **Limites do container:** 4 CPUs, 6 GB RAM
- **Motor:** Kokoro fp32 (ONNX), voz `pm_santa` — apenas CPU, sem GPU
- **Qwen3 nao foi usado** em nenhum benchmark devido a alta latencia em CPU
- **Formato de saida:** OGG Opus 24kbps 16kHz mono
- **Data:** 06/04/2026
