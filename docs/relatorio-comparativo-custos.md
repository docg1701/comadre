# Comadre vs TTS na Nuvem: Comparativo de Custo e Desempenho

**Documento da era v2 (2026-04).** Os números abaixo refletem a
implantação v2 (Kokoro fp32 + Qwen3-TTS). O Comadre 3.0.0 substituiu os
dois motores pelo pocket-tts da Kyutai (motor único + clonagem de voz)
em agosto de 2026. Um adendo v3 com números novos será anexado após o
cutover de produção e a re-execução do loadtest/capacity (Fase 4 do
plano de migração). Até lá, trate os valores como históricos.

## Resumo Executivo

O Comadre entrega áudio TTS ilimitado por um **custo mensal fixo de VPS** (a partir de ~$7/mês para uma única réplica e ~$21/mês para a configuração validada de duas réplicas), com **100% de integridade de áudio em 2.440 requisições de teste verificadas** cobrindo quatro configurações e uma carga de trabalho aleatorizada realista de chatbot. A vazão sustentável é de **~13 requisições por minuto em uma única réplica de 4 CPUs** e **~20 requisições por minuto em uma implantação de duas réplicas** (host de 8 CPUs, balanceamento de carga sensível à fila) — suficiente para alimentar de **27.000 a 42.000 conversas completas de atendimento ao cliente por WhatsApp por mês** sob padrões realistas de dia útil. A qualidade de voz é muito boa — comparável ao MiniMax, melhor que o Microsoft Edge TTS, e apenas ligeiramente abaixo dos melhores modelos da ElevenLabs. O projeto complementar kokoro-cloner permite vozes personalizadas de marca a partir de uma amostra de 10 segundos.

Para um negócio que atende 120 clientes/dia em português brasileiro, o Comadre custa **~99% menos que a ElevenLabs** e **~50% menos que a AI33.pro**, oferecendo ainda privacidade total de dados, conformidade com a LGPD por design e zero dependências externas. A diferença de custo aumenta drasticamente com o volume: em 211.000 áudios/mês (uma implantação de duas réplicas saturada), o Comadre custa ~$21/mês, enquanto o plano Scale da ElevenLabs + overage custa ~$4.646/mês e o tier EL/MM da AI33.pro custa ~$102/mês. A contrapartida é a necessidade de autogerenciar a infraestrutura e um catálogo de vozes menor comparado à ElevenLabs.

Todos os números de desempenho do Comadre neste relatório são medidos usando **apenas o motor Kokoro** (inferência em CPU, sem GPU). O Comadre também suporta Qwen3-TTS para clonagem de voz, mas o Qwen3 tem latência significativamente maior em CPU e só é viável para clientes de clonagem de voz com volume muito baixo (< 3 req/min) ou clientes dispostos a pagar por infraestrutura de GPU — veja as notas de seleção de motor abaixo. Os custos das plataformas na nuvem são calculados a partir dos preços publicados. A metodologia técnica profunda, a matriz de verificação de quatro vias (1 réplica vs 2 réplicas com ambas as políticas de balanceador de carga, vs 2 réplicas com CPU reduzida por réplica) e a correção de cegueira de fila que fechou a lacuna de escalabilidade estão documentadas em [docs/replica-scaling-report.md](replica-scaling-report.md).

## Perfis das Plataformas

### Comadre (Self-Hosted)

API TTS de código aberto com arquitetura de motor duplo, otimizada para português brasileiro. Roda em um VPS padrão sem necessidade de GPU.

- **Motor primário:** Kokoro fp32 — inferência rápida em CPU, sem necessidade de GPU. Todos os benchmarks deste relatório usam o Kokoro.
- **Motor secundário:** Qwen3-TTS C++ Q8_0 — capacidade de clonagem de voz para o tier de cliente que tem orçamento para GPU OU volume muito baixo (< 3 req/min). Não é usado nos benchmarks de vazão/custo porque não escala em CPU.
- **Implantação:** Docker Compose em qualquer VPS (mínimo 4 vCPU / 8 GB RAM para uma réplica; 8 vCPU / 16 GB RAM para a configuração recomendada de duas réplicas)
- **Modelo de preços:** Custo mensal fixo de VPS (~$7/mês para o tier de entrada de uma réplica, ~$21/mês para a configuração verificada de duas réplicas) ou próximo de zero em hardware self-hosted
- **API:** Compatível com OpenAI (`POST /v1/audio/speech`)
- **Idiomas:** Otimizado para português brasileiro (dicionário personalizado do espeak-ng, 67 entradas de siglas)
- **Balanceamento de carga (multi-réplica):** Reverse proxy Caddy com o resolvedor de upstream `dynamic a` e `lb_policy least_conn` — roteamento sensível à profundidade da fila que explora a arquitetura de lock FIFO único do Comadre para extrair a máxima vazão sustentada dos núcleos disponíveis (validado em 2026-04-11)

### ElevenLabs (SaaS na Nuvem)

TTS líder de mercado na nuvem com qualidade de voz premium e extensa biblioteca de vozes.

- **Modelo de preços:** Assinatura por tiers + overage por caractere

| Plano | Preço/mês | Caracteres | Minutos de áudio | Custo/min |
|------|----------|-----------|---------------|----------|
| Starter | $5 | 30.000 | ~30 | $0,167 |
| Creator | $22 | 100.000 | ~100 | $0,220 |
| Pro | $99 | 500.000 | ~500 | $0,198 |
| Scale | $330 | 2.000.000 | ~2.000 | $0,165 |
| Overage (Scale) | -- | -- | -- | $0,180/1k chars |

*~1.000 caracteres = 1 minuto de áudio (documentação da ElevenLabs).*

### AI33.pro (API na Nuvem)

Agregador de TTS na nuvem com orçamento reduzido que revende acesso a múltiplos provedores — ElevenLabs, MiniMax e Microsoft Edge TTS — através de um sistema unificado de créditos.

- **Provedores:** ElevenLabs (vozes premium), MiniMax (multilíngue), Microsoft Edge TTS (qualidade de tier gratuito)
- **Qualidade de voz:** Varia por provedor — as vozes da ElevenLabs são excelentes, MiniMax é muito boa, Edge é aceitável
- **Clonagem de voz:** Sim (via provedor ElevenLabs)
- **Idiomas:** Dezenas (herdados do suporte multilíngue ElevenLabs + MiniMax)
- **Modelo de preços:** Pacotes de créditos
- **Taxa:** $10 por 2.100.000 créditos
- **Custo por áudio (12s):** Edge ~90 créditos, ElevenLabs/MiniMax ~140-190 créditos
- **Taxa efetiva (ElevenLabs/MiniMax):** ~12.350 áudios por $10 = $0,00081/áudio
- **Taxa efetiva (Edge):** ~23.330 áudios por $10 = $0,00043/áudio
- **Custo por minuto de áudio:** $0,0041 (ElevenLabs/MiniMax), $0,0021 (Edge)
- **Contrapartida:** A qualidade depende do provedor. Edge é o mais barato, mas inferior ao Kokoro (sem clonagem, prosódia pior). ElevenLabs é a melhor qualidade mas custa 2x mais créditos. Para igualar a qualidade do Comadre é preciso o tier MiniMax/ElevenLabs — não o tier barato Edge. A latência e a disponibilidade dependem dos provedores upstream.

## Desempenho Medido (Comadre — Motor Kokoro)

Esta seção reporta dados de desempenho de duas campanhas de medição. Todos os dados usam o motor Kokoro (voz `kokoro/pm_santa`), inferência apenas em CPU, sem GPU. A metodologia técnica completa e a matriz de verificação estão em [docs/replica-scaling-report.md](replica-scaling-report.md).

**Ambiente de teste:** VM Proxmox, Xeon E5-2680v4, 8 vCPU compartilhadas / 16 GB RAM (configurável como uma única réplica de 4 CPUs ou duas réplicas de 4 CPUs via `deploy.replicas` no `compose.yaml`). Equivalente a um Hetzner CPX31 (4 vCPU compartilhadas, 8 GB) para o tier de réplica única ou CPX41 (8 vCPU compartilhadas, 16 GB) para o tier de duas réplicas.

### Campanhas de verificação

| Data | Carga de trabalho | Configurações medidas | Integridade do áudio |
|------|----------|------------------------|-----------------|
| 2026-04-06 | Corpus determinístico de 12 sentenças, ordenado por comprimento | 1 réplica × 4 CPU | 818/818 (100%) |
| 2026-04-11 | **Corpus aleatorizado de 24 sentenças** (tópicos variados, `random.choice` com seed para reprodutibilidade) | 4 configurações: 1r/4c, 2r/4c round_robin, 2r/4c **least_conn**, 2r/3c least_conn | 2.440/2.440 (100%) |

O reteste de 2026-04-11 com o corpus aleatorizado é **mais conservador** que a medição determinística mais antiga: as escolhas aleatórias adjacentes incluem rajadas de mensagens longas que o corpus ordenado suavizava. A vazão observada de réplica única caiu de 18 req/min (determinístico) para ~13 req/min (aleatorizado). Todos os números de dimensionamento e custo abaixo usam os **números conservadores aleatorizados** para que os clientes vejam a capacidade de pior caso.

### Vazão por configuração (2026-04-11)

| Configuração | Vazão sustentável | Taxa de produção de áudio | Observações |
|---|---|---|---|
| 1 réplica × 4 CPU | **~13 req/min** | ~1,7 min de áudio por minuto de relógio | Teto de instância única |
| 2 réplicas × 4 CPU, `round_robin` | ~19 req/min | ~2,5 min áudio/min | Política antiga padrão do balanceador de carga |
| **2 réplicas × 4 CPU, `least_conn`** | **~20 req/min** | **~2,6 min áudio/min** | **Recomendada** — roteamento sensível à fila |
| 2 réplicas × 3 CPU, `least_conn` | ~15 req/min (pior) | ~1,9 min áudio/min | Testada e rejeitada — CPU insuficiente por réplica |

A métrica correta para dimensionamento é a **taxa de produção de áudio** (minutos de áudio por minuto de relógio), porque toda réplica do Comadre é CPU-bound e produz uma quantidade aproximadamente constante de áudio por segundo. A vazão de requisições em req/min é derivada dessa taxa dividida pela duração média do áudio. Com nossa média medida de **7,74 segundos por áudio**, uma única réplica de 4 CPUs produz ~100 segundos de áudio por minuto de relógio (~13 req/min), e a configuração de duas réplicas produz ~155 segundos de áudio por minuto de relógio (~20 req/min).

### Latência por taxa de requisições (2026-04-11, latência média em segundos)

Medida com mensagens de áudio de 3,5–12,2 segundos (35–213 caracteres, média 7,74 s / 123 chars — variância realista de chatbot).

| Taxa alvo | Média 1 réplica | p50 1 réplica | Máx 1 réplica | Média 2 réplicas LC | p50 2 réplicas LC | Máx 2 réplicas LC |
|---|---|---|---|---|---|---|
| 2/min | 4,4s | 2,9s | 7,3s | 4,5s | 3,1s | 7,9s |
| 5/min | 5,2s | 5,5s | 7,2s | 4,9s | 5,4s | 7,7s |
| 10/min | 4,7s | 4,7s | 6,5s | 4,7s | 4,4s | 10,4s |
| 20/min | **36,6s** | 33,7s | 68,7s | **8,6s** | 8,1s | 17,5s |
| 30/min | **84,3s** | 84,0s | 165,5s | **37,8s** | 38,9s | 75,2s |
| 50/min | 177,3s | 170,5s | 335,6s | **95,3s** | 90,2s | 230,0s |
| 75/min | 280,5s | 272,0s | 624,8s | 162,8s | 160,7s | 331,4s |
| 100/min | 384,4s | 384,4s | 801,0s | 232,8s | 219,9s | 448,9s |

**Meta prática de SLA para atendimento ao cliente via WhatsApp: latência ≤ 90 segundos (média).** As respostas de áudio do WhatsApp são assíncronas — o cliente não fica encarando a tela esperando em tempo real, da mesma forma que uma resposta digitada em uma conversa profissional já leva 1+ minutos. Uma resposta de áudio gerada por TTS que leva 30–90 segundos é invisível contra o ritmo natural da conversa. Acima de 90 segundos o sistema começa a ficar estressado.

Sob esse SLA de 90 segundos, **uma única réplica de 4 CPUs aguenta até ~30 req/min** e **duas réplicas com `least_conn` aguentam até ~50 req/min**. Acima dessas taxas, a fila cresce mais rápido do que drena, a latência excede o SLA e é necessária uma configuração maior.

### Latência por tamanho de texto (requisição única, sem fila)

| Tamanho do texto | Caracteres | Duração do áudio | Tempo de geração |
|-----------|-----------|----------------|-----------------|
| Curto | ~50 | 2,5–3,5s | 1,4–1,7s |
| Médio (chatbot típico) | ~120 | 7–8s | 4–6s |
| Longo | ~200 | 11–13s | 5–7s |

### Uso de recursos

| Métrica | 1 réplica | 2 réplicas |
|--------|-----------|------------|
| Memória ociosa | ~570 MB | ~1.140 MB |
| Memória sob carga | ~1.028 MB estável | ~2.056 MB estável |
| Pico de memória (todos os testes) | 1.502 MB | ~3.000 MB |
| Vazamento de memória | Nenhum detectado | Nenhum detectado |
| CPU por réplica | 4 núcleos (100% durante geração) | 4 núcleos cada |
| CPU total na saturação | 4 núcleos | 8 núcleos |
| Quedas durante os testes | 0 | 0 |
| Corrupção de áudio | 0/610 (capacidade 1r) | 0/1.830 (capacidade 2r ao longo de 3 execuções) |

### O que o `least_conn` corrigiu (verificação de 2026-04-11)

A implantação de 2026-04-06 usava `lb_policy round_robin` para o caso multi-réplica. O round-robin é cego à fila: despacha novas requisições para as réplicas em rotação fixa, então quando uma réplica está ocupada com uma mensagem longa, a próxima requisição ainda vai para ela em vez da réplica ociosa. Trocar para `lb_policy least_conn` explora a arquitetura do Comadre: cada réplica processa requisições serialmente atrás de um único `asyncio.Lock`, e a conexão HTTP permanece aberta tanto durante a espera na fila quanto durante a inferência, então a "contagem de conexões ativas" do Caddy equivale exatamente à profundidade da fila + requisição em andamento em cada réplica. O `least_conn` é, portanto, literalmente sensível à profundidade da fila neste design.

Impacto medido (2 réplicas, teste de stress com concorrência 20):

| Métrica | round_robin | least_conn |
|---|---|---|
| Taxa de sucesso no cenário pesado | 60,0% | **91,1%** (+31,1pp, ~4,5x menos timeouts do cliente) |
| Latência média a 20 req/min | 12,1s | **8,6s** (−29%) |
| Latência média a 30 req/min | 36,3s | 37,8s (similar) |
| Vazão de saturação (50–100 req/min) | ~19,4 r/min | ~19,6 r/min (+1%) |

O ganho de vazão na saturação total é pequeno porque ambas as réplicas ficam fixadas em 100% de CPU independentemente da política. A grande vitória está no **regime de sobrecarga moderada** (concorrência logo acima do número de réplicas), onde o roteamento sensível à fila evita que uma réplica acumule backlog enquanto a outra fica ociosa. Esse regime é onde a maioria das cargas reais de produção se encontra.

## Comparativo de Custos

### Premissas

- **Dias úteis:** 22 por mês
- **Horas úteis:** 8 por dia
- **Duração média do áudio (medida):** 7,74 segundos, 123 caracteres (média de 1.830 saídas Kokoro verificadas do corpus aleatorizado de 2026-04-11, voz `kokoro/pm_santa`)
- **Mensagens por conversa de atendimento ao cliente via WhatsApp:** ~6 áudios (turnos profissionais típicos de 5–10 minutos com áudio dos dois lados)
- **Referência de custo do Comadre:** Preços de vCPU compartilhada do Hetzner Cloud em 2026 — ~$7/mês para um host de 4 vCPU (uma réplica), ~$21/mês para um host de 8 vCPU (duas réplicas com `least_conn`). O custo self-hosted em hardware existente é próximo de zero (apenas eletricidade).
- **Base de custo da ElevenLabs:** Plano Scale a $330/mês (2.000.000 chars inclusos) + $0,18 por 1.000 chars de overage. Conversão ~1.000 chars = 1 minuto de áudio segundo a documentação da ElevenLabs.
- **Base de custo da AI33.pro:** $10 por 2.100.000 créditos. Custo por caractere derivado da taxa de $10/2,1M créditos e dos custos publicados por áudio de 12s (90 créditos tier Edge; 140–190 créditos tier ElevenLabs/MiniMax). Com nossa média medida de 123 chars, isso resulta em ~$0,000264 por áudio (Edge) ou ~$0,000483 por áudio (EL/MM).

### Custo por nível de tráfego sustentado

Esta tabela mapeia o req/min sustentado de um cliente para a configuração Comadre recomendada e o custo mensal equivalente em cada plataforma. Os volumes assumem 8h × 22 dias úteis/mês na taxa sustentada listada.

| Perfil de cliente | Req/min sustentado | Áudios/mês | Minutos de áudio/mês | Config Comadre | Custo Comadre/mês | AI33.pro Edge | AI33.pro EL/MM | ElevenLabs Scale+ |
|---|---|---|---|---|---|---|---|---|
| Micro chatbot | 5 | 52.800 | 6.811 | 1 réplica × 4 CPU | **~$7** | $14 | $26 | $1.139 |
| Pequeno negócio | 10 | 105.600 | 13.622 | 1 réplica × 4 CPU | **~$7** | $28 | $51 | $2.308 |
| Negócio em crescimento | 13 (teto de 1r) | 137.280 | 17.709 | 1 réplica × 4 CPU | **~$7** | $36 | $66 | $3.009 |
| Operação grande | 20 (teto de 2r) | 211.200 | 27.245 | **2 réplicas × 4 CPU** | **~$21** | $56 | $102 | $4.646 |
| Alto volume | 28 | 295.680 | 38.143 | 3 réplicas × 4 CPU (extrapolado) | **~$30–45** | $78 | $143 | $6.516 |
| Volume muito alto | 38 | 401.280 | 51.765 | 4 réplicas × 4 CPU (extrapolado) | **~$45** | $106 | $194 | $8.854 |

As linhas de 1 e 2 réplicas são **medidas** (1.830 áudios verificados de ponta a ponta em 2026-04-11). As linhas de 3 e 4 réplicas são **extrapoladas** a partir da linearidade observada entre 1r e 2r (cada réplica adicional de 4 CPUs adiciona ~7 req/min de capacidade sustentada). A topologia de escalonamento recomendada é **um VPS maior com N réplicas**, não múltiplos VPS pequenos cada um rodando uma réplica — o escalonamento intra-host com `least_conn` validado em 2026-04-11 torna implantações multi-réplica em host único operacionalmente mais simples e ligeiramente mais baratas que a abordagem multi-VPS.

### Custo por minuto de áudio

| Plataforma | Custo/min no "Pequeno negócio" (10 req/min, ~227 horas de áudio/mês) | Custo/min na "Operação grande" (20 req/min, ~454 horas de áudio/mês) | Modelo de preços |
|----------|-------------|-------------|-------|
| **Comadre 1 réplica** | **$0,00051/min** | n/a (acima do teto de 1r) | VPS fixo |
| **Comadre 2 réplicas** | n/a (abaixo da utilização de 2r) | **$0,00077/min** | VPS fixo |
| AI33.pro Edge | $0,00204/min | $0,00204/min | Por crédito |
| AI33.pro EL/MM | $0,00375/min | $0,00375/min | Por crédito |
| ElevenLabs Scale+overage | ~$0,169/min | ~$0,171/min | Por caractere |

No tier "Operação grande" (20 req/min sustentado, ~454 horas de áudio por mês), o Comadre em um único VPS de 8 CPUs é **~5x mais barato que o tier AI33.pro Edge**, **~10x mais barato que o tier AI33.pro EL/MM** e **~220x mais barato que a ElevenLabs**. Acima desse tier a diferença aumenta ainda mais porque o custo marginal do Comadre é o próximo tier de upgrade de VPS (~$15–25 para dobrar a capacidade), enquanto a AI33.pro e a ElevenLabs escalam linearmente com o consumo para sempre.

### Por que o custo do Comadre permanece constante

A ElevenLabs e a AI33.pro cobram por áudio (por caractere ou por crédito, escalado ao comprimento). O custo delas cresce linearmente a cada minuto gerado — não há economia de escala além do limite do plano, apenas medição. Um cliente que 10x o seu volume vê a conta 10x.

O Comadre cobra o que o VPS cobra, ponto final. Gerar 200 horas de áudio por mês e gerar 800 horas por mês no mesmo VPS custa identicamente — o custo só muda quando você cruza uma fronteira de capacidade de hardware e precisa de um VPS maior. Cada tier de upgrade de VPS adiciona ~$15–25/mês em troca de ~150–410 horas adicionais de capacidade de áudio por mês. No menor tamanho viável (~$7/mês, 1 réplica) o Comadre já se paga vs ElevenLabs acima de ~300 áudios/mês, e vs AI33.pro acima de ~30.000 áudios/mês.

## Planejamento de Capacidade

O Comadre processa requisições sequencialmente por réplica (fila FIFO única por instância, `asyncio.Lock`). Múltiplas réplicas compartilham um host via o resolvedor de upstream `dynamic a` do Caddy e `lb_policy least_conn` (roteamento sensível à fila).

### Vazão sustentável por configuração de réplicas

Medida em 2026-04-11 com corpus aleatorizado realista de chatbot, áudio médio de 7,74 s.

| Configuração | Req/min sustentável | Máx sob SLA de 90s (latência média) | Taxa de produção de áudio |
|---|---|---|---|
| 1 réplica × 4 CPU | ~13 req/min | ~30 req/min | ~1,7 min de áudio por minuto de relógio |
| 2 réplicas × 4 CPU + `least_conn` | ~20 req/min | ~50 req/min | ~2,6 min de áudio por minuto de relógio |
| 3 réplicas × 4 CPU (extrapolado) | ~28 req/min | ~70 req/min | ~3,6 min de áudio por minuto de relógio |
| 4 réplicas × 4 CPU (extrapolado) | ~38 req/min | ~95 req/min | ~4,9 min de áudio por minuto de relógio |

A coluna "sustentável" é a taxa na qual a fila permanece limitada indefinidamente. A coluna "SLA de 90 s" é a taxa na qual a latência média por requisição permanece dentro do orçamento de turno WhatsApp de 90 segundos — confortavelmente acima da sustentável porque a sobrecarga moderada é absorvida pela fila sem exceder os 90 s de espera média. Cada réplica adicional de 4 CPUs adiciona aproximadamente 7 req/min de capacidade sustentada de forma linear.

### Quando adicionar réplicas / fazer upgrade do VPS

Para chatbots de WhatsApp, tempos médios de resposta de até 90 segundos estão bem dentro do ritmo natural de turnos de conversas profissionais e não são percebidos como atraso pelo cliente.

| Tamanho do negócio | Req/min sustentado | Config Comadre recomendada | Tamanho de VPS recomendado | Custo mensal |
|---|---|---|---|---|
| 50 clientes/dia, ~3 req/min | 3 | 1 réplica × 4 CPU | 4 vCPU / 8 GB compartilhadas | ~$7 |
| 120 clientes/dia, ~5 req/min | 5 | 1 réplica × 4 CPU | 4 vCPU / 8 GB compartilhadas | ~$7 |
| 300 clientes/dia, ~12 req/min | 12 | 1 réplica × 4 CPU (no teto) | 4 vCPU / 8 GB compartilhadas | ~$7 |
| 500 clientes/dia, ~20 req/min | 20 | **2 réplicas × 4 CPU + least_conn** | **8 vCPU / 16 GB compartilhadas** | **~$21** |
| 800 clientes/dia, ~28 req/min | 28 | 3 réplicas × 4 CPU | 12+ vCPU / 24 GB | ~$30–45 |
| 1.000 clientes/dia, ~40 req/min | 38 | 4 réplicas × 4 CPU | 16 vCPU / 32 GB | ~$45 |
| > 1.500 clientes/dia, > 50 req/min | 50+ | Multi-VPS ou host dedicado grande | Múltiplos hosts de 8 vCPU | $40–80 |

**Regra de dimensionamento que surgiu da verificação de 2026-04-11:** nunca dê a uma réplica Kokoro menos de 4 núcleos de CPU. Testamos 3 CPUs por réplica diretamente (Run D) e observamos ~22% de regressão de vazão sem nenhum benefício de latência — a inferência ONNX é CPU-bound e escala de forma próxima da linear até 4 núcleos. O layout ótimo é `replicas = floor(host_cpus / 4)`, deixando o Caddy e o kernel do host compartilharem o que sobrar de núcleos.

O escalonamento horizontal também pode ser feito adicionando *múltiplas instâncias de VPS* (cada uma rodando 1 réplica) atrás de um Caddy externo. Isso troca um pequeno prêmio de custo por isolamento de falhas mais forte: perder um VPS perde apenas 1/N da capacidade em vez de toda ela. Para a maioria dos clientes a abordagem multi-réplica em host único é mais simples e ligeiramente mais barata; multi-VPS é a escolha certa quando os alvos de uptime exigem domínios de falha independentes.

### Opção de Hardware Self-Hosted

Para negócios que possuem ou podem adquirir hardware, o Comadre roda em especificações mínimas (CPU de 4 núcleos, 4 GB RAM, qualquer máquina x86_64). Uma compra única de hardware (~$150-300 para um mini PC ou desktop reaproveitado) elimina o custo mensal de VPS completamente. O único custo recorrente é eletricidade (~$2-5/mês para um mini PC de baixo consumo).

| Implantação | Custo mensal | Total 1 ano | Total 2 anos |
|-----------|-------------|-------------|-------------|
| Hetzner VPS | $7/mês | $84 | $168 |
| Mini PC self-hosted | ~$3/mês (eletricidade) | ~$186 (hw + energia) | ~$222 |
| Self-hosted (hardware existente) | ~$3/mês (eletricidade) | $36 | $72 |

A auto-hospedagem empata com a hospedagem VPS após ~12 meses ao comprar novo hardware, ou é imediatamente mais barata se usar hardware existente.

## Latência e Confiabilidade

### Comadre: Previsível e Autocontrolado

Todo número abaixo é medido (corpus aleatorizado de 2026-04-11, voz `kokoro/pm_santa`).

| Condição | Tempo de resposta 1 réplica | Tempo de resposta 2 réplicas (`least_conn`) | Fonte |
|-----------|------------------------|----------------------------------------|--------|
| Sem fila (< 10 req/min) | 4–5 s média | 4–5 s média | Teste de capacidade |
| Carga leve (20 req/min) | 36 s média | **8,6 s média** | Teste de capacidade |
| Carga moderada (30 req/min) | 84 s média (no limite do SLA) | 38 s média | Teste de capacidade |
| Carga pesada (50 req/min) | 177 s média (acima do SLA) | **95 s média** (no limite do SLA) | Teste de capacidade |
| Concorrência pesada (20 simultâneas, stress de 5 min) | 27,7 % de sucesso (timeouts) | **91,1 % de sucesso** (vitória do `least_conn`) | Loadtest |
| Queda de servidor | 0 incidentes em 2.440+ requisições | 0 incidentes | Todos os testes |
| Corrupção de áudio | 0 incidentes em 2.440+ requisições | 0 incidentes | Todos os testes |

A latência do Comadre é determinística: depende apenas da profundidade da fila, que depende apenas do seu próprio tráfego. Nenhum outro cliente afeta o seu desempenho. A política `least_conn` adicionada na verificação de 2026-04-11 reduziu a taxa de timeouts sob concorrência pesada em ~4,5x comparada à política round-robin anterior, roteando cada nova requisição para a réplica que tem a menor fila naquele momento.

### Plataformas na Nuvem: Compartilhadas e Imprevisíveis

ElevenLabs e AI33.pro rodam em infraestrutura compartilhada. A latência delas depende de:

- Carga total de todos os clientes mundialmente
- Horário do dia (horário comercial em múltiplos fusos horários)
- Picos sazonais (Black Friday, campanhas de feriados)
- Incidentes da plataforma e janelas de manutenção
- Políticas de rate limiting que podem mudar sem aviso prévio

Nenhuma das plataformas publica garantias de SLA para tempo de resposta. Uma requisição que leva 2 segundos às 3 da manhã pode levar 30 segundos às 10 da manhã de uma segunda-feira.

**O Comadre elimina essa incerteza.** Você é o dono da infraestrutura, você mediu os limites e nenhum fator externo pode degradar o seu serviço.

## Comparativo de Funcionalidades

| Funcionalidade | Comadre | ElevenLabs | AI33.pro |
|---------|---------|------------|----------|
| **Qualidade de voz** | Muito boa (Kokoro) | Excelente | Varia (ElevenLabs/MiniMax/Edge) |
| **Otimização BR-PT** | Sim (dicionário personalizado) | Multilíngue genérico | Genérico (via provedores) |
| **Pronúncia de siglas** | Perfeita (67 entradas verificadas) | Inconsistente | Inconsistente (sem dicionário personalizado) |
| **Clonagem de voz** | Sim (Qwen3 + kokoro-cloner) | Sim (premium) | Sim (via provedor ElevenLabs) |
| **Voicepacks personalizados** | Sim (pipeline kokoro-cloner) | Não (clones predefinidos) | Não |
| **Vozes embutidas (pt-BR)** | 3 otimizadas + ilimitadas via kokoro-cloner | Centenas (multilíngue) | Centenas (de 3 provedores) |
| **Foco de idioma** | Apenas português brasileiro | Dezenas de idiomas | Dezenas (via ElevenLabs + MiniMax) |
| **Privacidade de dados** | Total (on-premise) | Nuvem (terceiros) | Nuvem (terceiros) |
| **Conformidade LGPD** | Inerente (dados não saem do seu servidor) | Requer DPA | Requer DPA |
| **Controle de uptime** | Você controla | Dependente do fornecedor | Dependente do fornecedor |
| **Dependência de rede** | Nenhuma (roda offline) | Requer internet | Requer internet |
| **Compatibilidade de API** | Compatível com OpenAI | Proprietária | Proprietária |
| **Previsibilidade de latência** | Medida, determinística | Variável, compartilhada | Variável, compartilhada |
| **Modelo de custo** | Mensal fixo | Por caractere | Por crédito |
| **Custo com 15k msgs/mês** | $7/mês | $330/mês | $13/mês |
| **Custo com 211k msgs/mês (~454h áudio)** | $21/mês (2 réplicas) | $4.646/mês | $102/mês (tier EL/MM) |
| **Escalonamento horizontal** | Manual (adicionar VPS) | Automático | Automático |
| **Complexidade de setup** | Média (Docker + Ansible) | Nenhuma (SaaS) | Baixa (chave de API) |
| **Manutenção** | Autogerenciada | Zero | Zero |

## Qualidade de Voz e Clonagem

### Posicionamento de Qualidade

O motor Kokoro do Comadre produz áudio de muito boa qualidade — comparável ao MiniMax e perceptivelmente melhor que o Microsoft Edge TTS. É apenas ligeiramente inferior aos modelos top-tier da ElevenLabs. A qualidade da AI33.pro varia dependendo de qual provedor é selecionado: as vozes ElevenLabs deles são excelentes, as vozes MiniMax são muito boas (comparáveis ao Comadre) e as vozes Edge são de qualidade perceptivelmente menor. Para mensagens de voz no WhatsApp, Telegram e Messenger, a diferença de qualidade entre o Comadre e o tier MiniMax da AI33.pro é desprezível. A ElevenLabs mantém vantagem em casos de uso premium como audiolivros, vozes de marca e vídeos de marketing.

### Clonagem de Voz Personalizada com kokoro-cloner

O projeto complementar [kokoro-cloner](https://github.com/docg1701/kokoro-cloner) cria voicepacks Kokoro personalizados a partir de uma amostra de voz de 10 segundos. O pipeline:

1. **Amplify** — Chatterbox clona a sua voz em 1.000 frases longas em pt-BR (5.000 WAVs de treinamento)
2. **Optimize** — A perda de embedding de locutor ECAPA-TDNN através do Kokoro congelado propaga de volta um vetor de estilo de 256 dimensões para igualar a sua voz
3. **Infer** — O Kokoro gera fala com o seu voicepack personalizado na velocidade total do Kokoro

O resultado é uma voz personalizada que roda na velocidade nativa do Kokoro (3-6 segundos por mensagem) sem penalidade de qualidade. Isso dá ao Comadre o melhor dos dois mundos: identidade de voz personalizada com a menor latência e custo.

Enquanto o Comadre vem com 3 vozes otimizadas para pt-BR, o kokoro-cloner permite **vozes personalizadas ilimitadas** — cada uma criada a partir de uma amostra de 10 segundos. O processo de clonagem roda uma vez, e o voicepack `.npy` resultante é colocado no diretório `/voices/kokoro/` do Comadre — disponível imediatamente, sem necessidade de reinicialização. Toda voz clonada herda a velocidade rápida de inferência e o baixo uso de recursos do Kokoro.

**Tempo de clonagem por hardware:**

| GPU | VRAM | Tempo estimado | Observações |
|-----|------|---------------|-------|
| RTX 2060 Super | 8 GB | ~6 horas | Medido. Gradient checkpointing ativado (limite de 8 GB) |
| RX 9060 XT | 16 GB | ~2-3 horas | Estimado. ~3x mais compute (RDNA 4), sem necessidade de gradient checkpointing (16 GB) |
| Apenas CPU | 8 GB RAM | ~24-48 horas | Sem GPU necessária, apenas mais lento |

A criação de voz é um custo único por voz. Uma vez gerado o voicepack, ele roda na velocidade nativa de inferência do Kokoro indefinidamente.

## Contrapartidas Honestas: Onde o Comadre Perde

### Catálogo de Vozes

O Comadre vem com 3 vozes otimizadas para pt-BR prontas de fábrica. Novas vozes são criadas via o pipeline kokoro-cloner a partir de uma amostra de 10 segundos (~6 horas em uma RTX 2060 Super, ~2-3 horas em uma RX 9060 XT). A ElevenLabs oferece centenas de vozes prontas para usar em dezenas de idiomas — basta escolher uma do catálogo instantaneamente, sem pipeline necessário. Para equipes que precisam de muitas vozes distintas rapidamente, a ElevenLabs tem uma vantagem prática.

### Setup e Manutenção

As plataformas na nuvem exigem zero gerenciamento de infraestrutura. O Comadre exige provisionar um VPS, rodar playbooks Ansible e ocasionalmente atualizar o serviço. Para equipes sem experiência em DevOps, isso é uma barreira real. A automação Ansible reduz isso a alguns comandos, mas não é zero.

### Escalonamento Automático

As plataformas na nuvem escalam de forma transparente. O Comadre exige adicionar instâncias VPS manualmente e configurar um balanceador de carga. Para negócios com picos de tráfego altamente imprevisíveis, esse processo manual adiciona sobrecarga operacional.

### Apenas Português

O Comadre é construído exclusivamente para português brasileiro — o pré-processamento de texto, o dicionário de siglas e o pós-processamento de áudio são todos específicos de pt-BR. Ele não suporta outros idiomas. Se você precisa de TTS multilíngue, a ElevenLabs é a única opção viável entre as três plataformas comparadas aqui.

## Quando Escolher Cada Opção

### Escolha o Comadre Quando

- **O volume excede 300 mensagens/mês** — ponto de equilíbrio vs ElevenLabs Starter
- **Privacidade de dados importa** — conversas dos clientes nunca saem do seu servidor (LGPD)
- **Custos previsíveis são essenciais** — $7/mês fixos independente do volume
- **Português brasileiro é o idioma principal** — dicionário personalizado de siglas, pronúncia testada
- **Você precisa de latência previsível** — medida, autocontrolada, sem infraestrutura compartilhada
- **Você quer uma voz de marca personalizada** — o kokoro-cloner cria um voicepack a partir de uma amostra de 10 segundos
- **Você tem capacidade básica de DevOps** — ou disposição para aprender Docker + Ansible
- **Você pode auto-hospedar** — hardware existente elimina os custos mensais completamente

### Escolha a ElevenLabs Quando

- **Qualidade de voz top-tier é inegociável** — audiolivros, narração premium de vídeo
- **Você precisa de muitos idiomas** — audiência global, suporte multi-idioma
- **O volume é abaixo de 300 mensagens/mês** — o plano Starter de $5/mês é difícil de bater
- **Zero gerenciamento de infraestrutura** — sem VPS, sem Docker, sem Ansible
- **Você precisa de clonagem instantânea de voz** — sem pipeline para rodar, clone pela interface

### Escolha a AI33.pro Quando

- **O orçamento é a restrição primária** — menor custo por áudio em baixo volume
- **O volume é abaixo de 8.000 mensagens/mês** — abaixo disso, a AI33 fica próxima do custo do Comadre
- **Você aceita os riscos de infraestrutura compartilhada** — latência não controlada, sem SLA
- **Simplicidade de setup importa mais que controle** — chave de API e pronto

## Apêndice: Metodologia dos Testes

Duas campanhas de medição informam este relatório. A matriz de verificação de quatro vias de 2026-04-11 é a fonte canônica para números de dimensionamento e custo porque usa uma carga de trabalho aleatorizada mais realista — os números mais antigos de 2026-04-06 permanecem referenciados onde adicionam contexto histórico. Detalhes completos e os dados tabela-por-tabela detalhados da matriz de quatro vias estão em [docs/replica-scaling-report.md](replica-scaling-report.md).

### Teste de saturação (`scripts/loadtest.py`)

- 6 cenários: baseline (concorrência 1), leve (3), moderado (10), pesado (20), stress (50), burst (30 simultâneas)
- ~370 requisições totais por execução (varia com a duração do cenário)
- Validação de áudio via ffprobe (duração > 0,1 s)
- Monitoramento de saúde a cada 1 segundo (profundidade da fila, memória)
- Timeout: 130 segundos por requisição (corresponde ao timeout de cliente estilo n8n no pior caso)
- Reteste de 2026-04-11: seed determinística (`--seed 42`) e seleção aleatória de corpus tornam as execuções reproduzíveis entre configurações

### Teste de capacidade (`scripts/capacity_test.py`)

- 8 tiers de taxa: 2, 5, 10, 20, 30, 50, 75, 100 requisições/minuto
- ~610 requisições totais por execução (8 tiers × 20 a 200 requisições por tier dependendo da taxa)
- Sem timeout de cliente — toda requisição espera até a conclusão, então o teste mede a latência sob pressão sustentada em vez de timeouts no lado do cliente
- Reteste de 2026-04-11: mesmo corpus aleatorizado com seed, mesmos tiers de taxa, executado contra quatro configurações (1r/4c, 2r/4c round_robin, 2r/4c least_conn, 2r/3c least_conn)

### Corpus de texto

- **2026-04-06:** 12 sentenças em português brasileiro (80–200 caracteres, áudio de 5–12 segundos), selecionadas deterministicamente por `text = TEXTS[req_id % len(TEXTS)]` — ordenadas por comprimento, então cada volta de 12 requisições entregava o mesmo formato `5-curtas + 4-médias + 3-longas`
- **2026-04-11:** 24 sentenças em português brasileiro cobrindo a mesma janela de áudio de 5–12 segundos mas cobrindo tópicos variados (pedidos, envio, métodos de pagamento, trocas, suporte, agendamento, fidelidade, NF-e) e saudações variadas (Oi, Olá, Bom dia, Boa tarde, Boa noite, sem saudação). A seleção agora usa uma instância `random.Random(seed)` com seed compartilhada entre todos os tiers, com os textos pré-computados por tier de forma que a sequência seja totalmente determinística independentemente do agendamento do asyncio.
- Duração média do áudio medida em 1.830 saídas verificadas de 2026-04-11: **7,74 segundos** (média de 123 caracteres, ~16 chars/segundo de áudio)

### Ambiente

- **Host (2026-04-06):** VM Proxmox 9.1.7 em Xeon E5-2680v4, equivalente a um Hetzner CPX31 (4 vCPU compartilhadas / 8 GB RAM). Limites do container: 4 CPU, 6 GB RAM.
- **Host (2026-04-11):** Mesmo hardware Proxmox/Xeon E5-2680v4, configuração de VPS implantada — 8 vCPU compartilhadas / 16 GB RAM. Limites do container por réplica: 4 CPU, 6 GB RAM. As configurações de duas réplicas usam ambas as réplicas do `tts-service` atrás de um único reverse proxy Caddy.
- **Motor:** Kokoro fp32 (ONNX), voz `kokoro/pm_santa` — apenas CPU, sem GPU.
- **Qwen3 não foi usado** em nenhum benchmark de vazão — veja as notas de seleção de motor no resumo executivo para o motivo.
- **Formato de saída:** OGG Opus 24 kbps, 16 kHz mono.
- **Integridade de áudio (2026-04-11):** 2.440 de 2.440 requisições em todas as quatro configurações produziram arquivos de áudio válidos (verificados com `ffprobe`). Zero quedas, zero saídas corrompidas.
- **Datas de teste:** 2026-04-06 (réplica única inicial), 2026-04-11 (verificação multi-réplica de quatro vias)
