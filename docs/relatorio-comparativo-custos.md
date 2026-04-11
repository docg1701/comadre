# Comadre vs TTS na Nuvem: Comparativo de Custo e Desempenho

## Resumo Executivo

O Comadre entrega audio TTS ilimitado por um **custo mensal fixo de VPS** (a partir de ~$7/mes para uma unica replica, ate ~$21/mes para a configuracao validada com duas replicas), com **100% de integridade de audio em 2.440 requisicoes de teste validadas** em quatro configuracoes diferentes e usando uma carga de trabalho realista randomizada de chatbot. A vazao sustentavel e de **~13 requisicoes por minuto em uma unica replica de 4 CPU** e **~20 requisicoes por minuto em uma implantacao de duas replicas** (host de 8 CPU, com balanceamento de carga ciente da fila) — capacidade suficiente para sustentar **27.000 a 42.000 atendimentos completos de WhatsApp por mes** em padroes realistas de jornada de trabalho. A qualidade de voz e muito boa — comparavel ao MiniMax, superior ao Microsoft Edge TTS e apenas ligeiramente inferior aos melhores modelos da ElevenLabs. O projeto complementar kokoro-cloner permite criar vozes personalizadas a partir de uma amostra de 10 segundos.

Para um negocio que atende 120 clientes/dia em portugues brasileiro, o Comadre custa **~99% menos que a ElevenLabs** e **~50% menos que o AI33.pro**, oferecendo privacidade total dos dados, conformidade com a LGPD por design e zero dependencias externas. O abismo de custo cresce drasticamente com o volume: a 211.000 audios/mes (uma implantacao saturada de duas replicas), o Comadre custa ~$21/mes enquanto a ElevenLabs Scale + excedente custa ~$4.646/mes e o AI33.pro tier EL/MM custa ~$102/mes. A contrapartida e a necessidade de gerenciar a propria infraestrutura e um catalogo de vozes menor em comparacao com a ElevenLabs.

Todos os numeros de desempenho do Comadre neste relatorio foram medidos usando exclusivamente o **motor Kokoro** (inferencia em CPU, sem GPU). O Comadre tambem suporta Qwen3-TTS para clonagem de voz, mas o Qwen3 tem latencia significativamente maior em CPU e so e viavel para clientes de clonagem de voz com volume muito baixo (< 3 req/min) ou clientes dispostos a pagar por infraestrutura GPU — veja as notas de selecao de motor abaixo. Os custos das plataformas na nuvem sao calculados a partir dos precos publicados. A metodologia tecnica completa, a matriz de verificacao de quatro configuracoes (1 replica vs 2 replicas com ambas as politicas de balanceador, vs 2 replicas com CPU reduzida) e a correcao de queue-blindness que fechou o gap de escalabilidade estao documentadas em [docs/replica-scaling-report.md](replica-scaling-report.md).

## Perfil das Plataformas

### Comadre (Self-Hosted)

API TTS de codigo aberto com dois motores, otimizada para portugues brasileiro. Roda em um VPS padrao sem necessidade de GPU.

- **Motor principal:** Kokoro fp32 — inferencia rapida em CPU, sem GPU. Todos os benchmarks deste relatorio usam o Kokoro.
- **Motor secundario:** Qwen3-TTS C++ Q8_0 — capacidade de clonagem de voz, voltada ao tier de cliente que tem orcamento de GPU OU volume muito baixo (< 3 req/min). Nao usado nos benchmarks de vazao/custo porque nao escala em CPU.
- **Deploy:** Docker Compose em qualquer VPS (minimo 4 vCPU / 8 GB RAM para uma replica; 8 vCPU / 16 GB RAM para a configuracao recomendada de duas replicas)
- **Modelo de preco:** Custo fixo mensal de VPS (~$7/mes para o tier de entrada com uma replica, ~$21/mes para a configuracao verificada com duas replicas) ou custo quase zero em hardware proprio
- **API:** Compativel com OpenAI (`POST /v1/audio/speech`)
- **Idiomas:** Otimizado para portugues brasileiro (dicionario personalizado espeak-ng, 67 siglas cadastradas)
- **Balanceamento de carga (multi-replica):** Reverse proxy Caddy com `dynamic a` upstream resolver e `lb_policy least_conn` — roteamento ciente da profundidade da fila que aproveita a arquitetura de fila FIFO unica do Comadre para extrair a vazao maxima sustentada dos cores disponiveis (validado em 2026-04-11)

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

Esta secao apresenta dados de duas campanhas de medicao. Todos os dados usam o motor Kokoro (voz `kokoro/pm_santa`), inferencia apenas em CPU, sem GPU. A metodologia tecnica completa e a matriz de verificacao estao em [docs/replica-scaling-report.md](replica-scaling-report.md).

**Ambiente de teste:** VM Proxmox, Xeon E5-2680v4, 8 vCPU compartilhados / 16 GB RAM (configuravel como uma replica de 4 CPU ou duas replicas de 4 CPU via `deploy.replicas` no `compose.yaml`). Equivalente a um Hetzner CPX31 (4 vCPU compartilhados, 8 GB) para o tier de uma replica ou CPX41 (8 vCPU compartilhados, 16 GB) para o tier de duas replicas.

### Campanhas de verificacao

| Data | Carga de trabalho | Configuracoes medidas | Integridade de audio |
|------|-------------------|----------------------|---------------------|
| 06/04/2026 | Corpus deterministico de 12 frases, ordenado por tamanho | 1 replica × 4 CPU | 818/818 (100%) |
| 11/04/2026 | **Corpus randomizado de 24 frases** (topicos variados, `random.choice` com seed para reprodutibilidade) | 4 configuracoes: 1r/4c, 2r/4c round_robin, 2r/4c **least_conn**, 2r/3c least_conn | 2.440/2.440 (100%) |

O reteste de 11/04/2026 com o corpus randomizado e **mais conservador** que a medicao deterministica anterior: escolhas aleatorias adjacentes incluem rajadas de mensagens longas que o corpus ordenado suavizava. A vazao observada para uma replica caiu de 18 req/min (deterministico) para ~13 req/min (randomizado). Todas as cifras de sizing e custo abaixo usam os **numeros conservadores randomizados** para que os clientes vejam a capacidade no pior caso.

### Vazao por configuracao (11/04/2026)

| Configuracao | Vazao sustentavel | Taxa de producao de audio | Observacoes |
|---|---|---|---|
| 1 replica × 4 CPU | **~13 req/min** | ~1,7 min de audio por minuto wall-clock | Teto de instancia unica |
| 2 replicas × 4 CPU, `round_robin` | ~19 req/min | ~2,5 min audio/min | Politica antiga padrao do balanceador |
| **2 replicas × 4 CPU, `least_conn`** | **~20 req/min** | **~2,6 min audio/min** | **Recomendado** — roteamento ciente da fila |
| 2 replicas × 3 CPU, `least_conn` | ~15 req/min (pior) | ~1,9 min audio/min | Testado e rejeitado — CPU insuficiente por replica |

A metrica correta para sizing e a **taxa de producao de audio** (minutos de audio por minuto de wall-clock), porque cada replica do Comadre e CPU-bound e produz uma quantidade aproximadamente constante de audio por segundo. A vazao em req/min e derivada dessa taxa dividida pela duracao media do audio. Com a media medida de **7,74 segundos por audio**, uma unica replica de 4 CPU produz ~100 segundos de audio por minuto wall-clock (~13 req/min), e a configuracao de duas replicas produz ~155 segundos de audio por minuto (~20 req/min).

### Latencia por taxa de requisicoes (11/04/2026, latencia media em segundos)

Medido com mensagens de audio de 3,5-12,2 segundos (35-213 caracteres, media 7,74s / 123 chars — variancia realista de chatbot).

| Taxa alvo | 1 replica media | 1 replica p50 | 1 replica max | 2 replicas LC media | 2 replicas LC p50 | 2 replicas LC max |
|---|---|---|---|---|---|---|
| 2/min | 4,4s | 2,9s | 7,3s | 4,5s | 3,1s | 7,9s |
| 5/min | 5,2s | 5,5s | 7,2s | 4,9s | 5,4s | 7,7s |
| 10/min | 4,7s | 4,7s | 6,5s | 4,7s | 4,4s | 10,4s |
| 20/min | **36,6s** | 33,7s | 68,7s | **8,6s** | 8,1s | 17,5s |
| 30/min | **84,3s** | 84,0s | 165,5s | **37,8s** | 38,9s | 75,2s |
| 50/min | 177,3s | 170,5s | 335,6s | **95,3s** | 90,2s | 230,0s |
| 75/min | 280,5s | 272,0s | 624,8s | 162,8s | 160,7s | 331,4s |
| 100/min | 384,4s | 384,4s | 801,0s | 232,8s | 219,9s | 448,9s |

**Meta pratica de SLA para atendimento WhatsApp: latencia <= 90 segundos (media).** Respostas em audio no WhatsApp sao assincronas — o cliente nao esta olhando para a tela esperando em tempo real, da mesma forma que uma resposta digitada bem feita em uma conversa profissional ja leva 1+ minuto. Uma resposta de audio gerada por TTS que leva 30-90 segundos e invisivel diante do ritmo conversacional natural. Acima de 90 segundos o sistema esta comecando a ficar estressado.

Sob essa meta de SLA de 90 segundos, **uma unica replica de 4 CPU sustenta ate ~30 req/min** e **duas replicas com `least_conn` sustentam ate ~50 req/min**. Acima dessas taxas, a fila cresce mais rapido do que drena, a latencia excede o SLA, e uma configuracao maior e necessaria.

### Latencia por tamanho do texto (requisicao unica, sem fila)

| Tamanho | Caracteres | Duracao do audio | Tempo de geracao |
|---------|-----------|-----------------|-----------------|
| Curto | ~50 | 2,5-3,5s | 1,4-1,7s |
| Medio (chatbot tipico) | ~120 | 7-8s | 4-6s |
| Longo | ~200 | 11-13s | 5-7s |

### Uso de recursos

| Metrica | 1 replica | 2 replicas |
|---------|-----------|------------|
| Memoria em repouso | ~570 MB | ~1.140 MB |
| Memoria sob carga | ~1.028 MB estavel | ~2.056 MB estavel |
| Pico de memoria (todos os testes) | 1.502 MB | ~3.000 MB |
| Vazamento de memoria | Nenhum detectado | Nenhum detectado |
| CPU por replica | 4 nucleos (100% durante geracao) | 4 nucleos cada |
| CPU total em saturacao | 4 nucleos | 8 nucleos |
| Crashes durante testes | 0 | 0 |
| Corrupcao de audio | 0/610 (1r capacidade) | 0/1.830 (2r capacidade em 3 runs) |

### O que o `least_conn` resolveu (verificacao 11/04/2026)

A implantacao de 06/04/2026 usava `lb_policy round_robin` no caso multi-replica. Round-robin e cego a fila: ele despacha novas requisicoes para as replicas em rotacao fixa, entao quando uma replica esta ocupada com uma mensagem longa, a proxima requisicao ainda vai para ela em vez da replica ociosa. Trocar para `lb_policy least_conn` aproveita a arquitetura do Comadre: cada replica processa requisicoes serialmente atras de um unico `asyncio.Lock`, e a conexao HTTP fica aberta tanto durante a espera na fila quanto durante a inferencia, entao a contagem de "conexoes ativas" do Caddy e exatamente igual a profundidade da fila + requisicao em voo em cada replica. O `least_conn` e portanto literalmente ciente da profundidade da fila neste design.

Impacto medido (2 replicas, teste de stress de concorrencia 20):

| Metrica | round_robin | least_conn |
|---|---|---|
| Taxa de sucesso do cenario heavy | 60,0% | **91,1%** (+31,1pp, ~4,5x menos timeouts no cliente) |
| Latencia media a 20 req/min | 12,1s | **8,6s** (-29%) |
| Latencia media a 30 req/min | 36,3s | 37,8s (similar) |
| Vazao em saturacao (50-100 req/min) | ~19,4 r/min | ~19,6 r/min (+1%) |

O ganho de vazao em saturacao plena e pequeno porque ambas as replicas estao em 100% de CPU independente da politica. A grande vitoria esta no **regime de sobrecarga moderada** (concorrencia logo acima do numero de replicas), onde o roteamento ciente da fila evita que uma replica acumule backlog enquanto a outra fica ociosa. Esse e o regime onde a maioria das cargas reais de producao se encontra.

## Comparativo de Custos

### Premissas

- **Dias uteis:** 22 por mes
- **Horas de trabalho:** 8 por dia
- **Duracao media do audio (medida):** 7,74 segundos, 123 caracteres (media de 1.830 saidas Kokoro verificadas do corpus randomizado de 11/04/2026, voz `kokoro/pm_santa`)
- **Mensagens por atendimento WhatsApp:** ~6 audios (conversa profissional tipica de 5-10 minutos com audio dos dois lados)
- **Referencia de custo Comadre:** Precos Hetzner Cloud com vCPU compartilhado em 2026 — ~$7/mes para um host de 4 vCPU (uma replica), ~$21/mes para um host de 8 vCPU (duas replicas com `least_conn`). Custo self-hosted em hardware existente e quase zero (apenas eletricidade).
- **Base de custo ElevenLabs:** Plano Scale a $330/mes (2.000.000 chars inclusos) + $0,18 por 1.000 chars excedentes. Conversao ~1.000 chars = 1 minuto de audio segundo a documentacao da ElevenLabs.
- **Base de custo AI33.pro:** $10 por 2.100.000 creditos. Custo por caractere derivado da taxa de $10/2,1M creditos e dos custos publicados de creditos por audio de 12s (90 creditos tier Edge; 140-190 creditos tier ElevenLabs/MiniMax). Na nossa media medida de 123 caracteres, isso resulta em ~$0,000264 por audio (Edge) ou ~$0,000483 por audio (EL/MM).

### Custo por nivel de trafego sustentado

Esta tabela mapeia a taxa sustentada em req/min do cliente para a configuracao Comadre recomendada e o custo mensal equivalente em cada plataforma. Volumes assumem 8h × 22 dias uteis/mes na taxa sustentada listada.

| Perfil de cliente | Req/min sustentadas | Audios/mes | Minutos de audio/mes | Config Comadre | Comadre $/mes | AI33.pro Edge | AI33.pro EL/MM | ElevenLabs Scale+ |
|---|---|---|---|---|---|---|---|---|
| Micro chatbot | 5 | 52.800 | 6.811 | 1 replica × 4 CPU | **~$7** | $14 | $26 | $1.139 |
| Pequeno | 10 | 105.600 | 13.622 | 1 replica × 4 CPU | **~$7** | $28 | $51 | $2.308 |
| Em crescimento | 13 (teto 1r) | 137.280 | 17.709 | 1 replica × 4 CPU | **~$7** | $36 | $66 | $3.009 |
| Grande operacao | 20 (teto 2r) | 211.200 | 27.245 | **2 replicas × 4 CPU** | **~$21** | $56 | $102 | $4.646 |
| Tier alto | 28 | 295.680 | 38.143 | 3 replicas × 4 CPU (extrapolado) | **~$30-45** | $78 | $143 | $6.516 |
| Tier muito alto | 38 | 401.280 | 51.765 | 4 replicas × 4 CPU (extrapolado) | **~$45** | $106 | $194 | $8.854 |

As linhas de 1 e 2 replicas sao **medidas** (1.830 audios verificados ponta-a-ponta em 11/04/2026). As linhas de 3 e 4 replicas sao **extrapoladas** da linearidade observada entre 1r e 2r (cada replica adicional de 4 CPU adiciona ~7 req/min de capacidade sustentada). A topologia de escalabilidade recomendada e **um VPS maior com N replicas**, nao multiplos VPSs pequenos cada um rodando uma replica — a escalabilidade intra-host com `least_conn` validada em 11/04/2026 torna implantacoes single-host multi-replica operacionalmente mais simples e ligeiramente mais baratas que a abordagem multi-VPS.

### Custo por minuto de audio

| Plataforma | Custo/min em "Pequeno" (10 req/min, ~227h audio/mes) | Custo/min em "Grande operacao" (20 req/min, ~454h audio/mes) | Modelo de preco |
|------------|-------------|-------------|-------|
| **Comadre 1 replica** | **$0,00051/min** | n/a (acima do teto 1r) | VPS fixo |
| **Comadre 2 replicas** | n/a (abaixo da utilizacao 2r) | **$0,00077/min** | VPS fixo |
| AI33.pro Edge | $0,00204/min | $0,00204/min | Por credito |
| AI33.pro EL/MM | $0,00375/min | $0,00375/min | Por credito |
| ElevenLabs Scale+excedente | ~$0,169/min | ~$0,171/min | Por caractere |

No tier "Grande operacao" (20 req/min sustentadas, ~454 horas de audio por mes), o Comadre em um unico VPS de 8 CPU e **~5x mais barato que o AI33.pro tier Edge**, **~10x mais barato que o AI33.pro tier EL/MM**, e **~220x mais barato que a ElevenLabs**. Acima desse tier o gap so aumenta porque o custo marginal do Comadre e o proximo upgrade de VPS (~$15-25 para dobrar a capacidade), enquanto o AI33.pro e a ElevenLabs escalam linearmente com o consumo para sempre.

### Por que o custo do Comadre fica fixo

ElevenLabs e AI33.pro cobram por audio (por caractere ou por credito, escalado pelo tamanho). O custo deles cresce linearmente com cada minuto gerado — nao ha economia de escala alem do limite do plano, apenas medicao. Um cliente que aumenta o volume em 10x ve a conta crescer 10x.

O Comadre cobra o que o VPS cobra, ponto final. Gerar 200 horas de audio por mes e gerar 800 horas por mes no mesmo VPS custa identicamente — o custo so muda quando voce cruza um limite de capacidade de hardware e precisa de um VPS maior. Cada upgrade de VPS adiciona ~$15-25/mes em troca de ~150-410 horas adicionais de capacidade de audio por mes. No menor tamanho viavel (~$7/mes, 1 replica) o Comadre ja se paga vs ElevenLabs acima de ~300 audios/mes, e vs AI33.pro acima de ~30.000 audios/mes.

## Planejamento de Capacidade

O Comadre processa requisicoes sequencialmente por replica (fila FIFO unica por instancia, `asyncio.Lock`). Multiplas replicas compartilham um host via o resolver `dynamic a` upstream do Caddy e `lb_policy least_conn` (roteamento ciente da fila).

### Vazao sustentavel por configuracao

Medido em 11/04/2026 com corpus de chatbot randomizado realista, audio medio de 7,74s.

| Configuracao | Req/min sustentadas | Maximo sob SLA de 90s (latencia media) | Taxa de producao de audio |
|---|---|---|---|
| 1 replica × 4 CPU | ~13 req/min | ~30 req/min | ~1,7 min audio por minuto wall-clock |
| 2 replicas × 4 CPU + `least_conn` | ~20 req/min | ~50 req/min | ~2,6 min audio por minuto wall-clock |
| 3 replicas × 4 CPU (extrapolado) | ~28 req/min | ~70 req/min | ~3,6 min audio por minuto wall-clock |
| 4 replicas × 4 CPU (extrapolado) | ~38 req/min | ~95 req/min | ~4,9 min audio por minuto wall-clock |

A coluna "sustentavel" e a taxa em que a fila permanece limitada indefinidamente. A coluna "SLA 90s" e a taxa em que a latencia media por requisicao se mantem dentro do orcamento de 90 segundos do ritmo de turn-taking do WhatsApp — confortavelmente acima do sustentavel porque a sobrecarga moderada e absorvida pela fila sem exceder os 90s de espera media. Cada replica adicional de 4 CPU adiciona aproximadamente 7 req/min de capacidade sustentada de forma linear.

### Quando adicionar replicas / fazer upgrade do VPS

Para chatbots WhatsApp, tempos medios de resposta ate 90 segundos estao bem dentro do ritmo natural de turn-taking de conversas profissionais e nao sao percebidos como atraso pelo cliente.

| Porte do negocio | Req/min sustentadas | Config Comadre recomendada | Tamanho do VPS recomendado | Custo mensal |
|---|---|---|---|---|
| 50 clientes/dia, ~3 req/min | 3 | 1 replica × 4 CPU | 4 vCPU / 8 GB compartilhado | ~$7 |
| 120 clientes/dia, ~5 req/min | 5 | 1 replica × 4 CPU | 4 vCPU / 8 GB compartilhado | ~$7 |
| 300 clientes/dia, ~12 req/min | 12 | 1 replica × 4 CPU (no teto) | 4 vCPU / 8 GB compartilhado | ~$7 |
| 500 clientes/dia, ~20 req/min | 20 | **2 replicas × 4 CPU + least_conn** | **8 vCPU / 16 GB compartilhado** | **~$21** |
| 800 clientes/dia, ~28 req/min | 28 | 3 replicas × 4 CPU | 12+ vCPU / 24 GB | ~$30-45 |
| 1.000 clientes/dia, ~40 req/min | 38 | 4 replicas × 4 CPU | 16 vCPU / 32 GB | ~$45 |
| > 1.500 clientes/dia, > 50 req/min | 50+ | Multi-VPS ou host dedicado grande | Multiplos hosts 8 vCPU | $40-80 |

**Regra de sizing que saiu da verificacao de 11/04/2026:** nunca de menos de 4 nucleos de CPU por replica do Kokoro. Testado 3 CPU por replica diretamente (Run D) e observado regressao de ~22% na vazao sem beneficio de latencia — inferencia ONNX e CPU-bound e escala quase linearmente ate 4 cores. O layout otimo e `replicas = floor(host_cpus / 4)`, deixando o Caddy e o kernel do host compartilharem os cores restantes.

A escalabilidade horizontal tambem pode ser feita adicionando *multiplas instancias VPS* (cada uma rodando 1 replica) atras de um Caddy externo. Isso troca um pequeno custo adicional por isolamento mais forte de falhas: perder um VPS perde apenas 1/N da capacidade ao inves de toda. Para a maioria dos clientes a abordagem single-host multi-replica e mais simples e ligeiramente mais barata; multi-VPS e a escolha certa quando metas de uptime exigem dominios de falha independentes.

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

Todos os numeros abaixo foram medidos (corpus randomizado de 11/04/2026, voz `kokoro/pm_santa`).

| Condicao | Tempo de resposta 1 replica | Tempo de resposta 2 replicas (`least_conn`) | Fonte |
|----------|---------------------------|----------------------------------------------|-------|
| Sem fila (< 10 req/min) | 4-5s media | 4-5s media | Teste de capacidade |
| Carga leve (20 req/min) | 36s media | **8,6s media** | Teste de capacidade |
| Carga moderada (30 req/min) | 84s media (no limite do SLA) | 38s media | Teste de capacidade |
| Carga pesada (50 req/min) | 177s media (acima do SLA) | **95s media** (no limite do SLA) | Teste de capacidade |
| Concorrencia pesada (20 simultaneas, stress de 5 min) | 27,7% de sucesso (timeouts) | **91,1% de sucesso** (vitoria do `least_conn`) | Loadtest |
| Crash do servidor | 0 incidentes em 2.440+ requisicoes | 0 incidentes | Todos os testes |
| Corrupcao de audio | 0 incidentes em 2.440+ requisicoes | 0 incidentes | Todos os testes |

A latencia do Comadre e deterministica: depende apenas da profundidade da fila, que depende apenas do seu proprio trafego. Nenhum outro cliente afeta o seu desempenho. A politica `least_conn` adicionada na verificacao de 11/04/2026 reduziu a taxa de timeouts em concorrencia pesada em ~4,5x comparado a politica round-robin anterior, roteando cada nova requisicao para a replica que tem a fila mais curta naquele momento.

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
| **Custo com 211k msgs/mes (~454h audio)** | $21/mes (2 replicas) | $4.646/mes | $102/mes (tier EL/MM) |
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

Duas campanhas de medicao informam este relatorio. A matriz de verificacao de quatro configuracoes de 11/04/2026 e a fonte canonica para sizing e cifras de custo porque usa uma carga de trabalho randomizada mais realista — os numeros mais antigos de 06/04/2026 permanecem referenciados onde adicionam contexto historico. Detalhes completos e os dados tabela-por-tabela detalhados da matriz de quatro configuracoes estao em [docs/replica-scaling-report.md](replica-scaling-report.md).

### Teste de saturacao (`scripts/loadtest.py`)

- 6 cenarios: baseline (concorrencia 1), leve (3), moderado (10), pesado (20), stress (50), rajada (30 simultaneas)
- ~370 requisicoes totais por run (varia com a duracao do cenario)
- Validacao de audio via ffprobe (duracao > 0,1s)
- Monitoramento de saude a cada 1 segundo (profundidade da fila, memoria)
- Timeout: 130 segundos por requisicao (corresponde ao pior caso de timeout de cliente estilo n8n)
- Reteste de 11/04/2026: seed deterministica (`--seed 42`) e selecao de corpus randomizada tornam runs reproduziveis entre configuracoes

### Teste de capacidade (`scripts/capacity_test.py`)

- 8 niveis de taxa: 2, 5, 10, 20, 30, 50, 75, 100 requisicoes/minuto
- ~610 requisicoes totais por run (8 niveis × 20 a 200 requisicoes por nivel dependendo da taxa)
- Sem timeout no cliente — cada requisicao espera ate ser completada, entao o teste mede latencia sob pressao sustentada em vez de timeouts no lado cliente
- Reteste de 11/04/2026: mesmo corpus randomizado com seed, mesmos niveis de taxa, executado contra quatro configuracoes (1r/4c, 2r/4c round_robin, 2r/4c least_conn, 2r/3c least_conn)

### Corpus de texto

- **06/04/2026:** 12 frases em portugues brasileiro (80-200 caracteres, audio de 5-12 segundos), selecionadas deterministicamente por `text = TEXTS[req_id % len(TEXTS)]` — ordenadas por tamanho, entao cada lap de 12 requisicoes entregava o mesmo formato `5-curtas + 4-medias + 3-longas`
- **11/04/2026:** 24 frases em portugues brasileiro abrangendo a mesma janela de audio de 5-12 segundos mas cobrindo topicos variados (pedidos, frete, formas de pagamento, devolucoes, suporte, agendamento, fidelidade, NF-e) e saudacoes variadas (Oi, Ola, Bom dia, Boa tarde, Boa noite, sem saudacao). A selecao agora usa uma instancia `random.Random(seed)` com seed compartilhada entre todos os niveis, com textos pre-computados por nivel para que a sequencia seja totalmente deterministica independente do scheduling do asyncio.
- Duracao media de audio medida em 1.830 saidas verificadas de 11/04/2026: **7,74 segundos** (123 caracteres em media, ~16 chars/segundo de audio)

### Ambiente

- **Host (06/04/2026):** VM Proxmox 9.1.7 com Xeon E5-2680v4, equivalente a um Hetzner CPX31 (4 vCPU compartilhados / 8 GB RAM). Limites do container: 4 CPU, 6 GB RAM.
- **Host (11/04/2026):** Mesmo hardware Proxmox/Xeon E5-2680v4, configuracao de VPS implantado — 8 vCPU compartilhados / 16 GB RAM. Limites por replica do container: 4 CPU, 6 GB RAM. Configuracoes de duas replicas usam ambas as replicas do `tts-service` atras de um unico Caddy.
- **Motor:** Kokoro fp32 (ONNX), voz `kokoro/pm_santa` — apenas CPU, sem GPU.
- **Qwen3 nao foi usado** em nenhum benchmark de vazao — veja as notas de selecao de motor no resumo executivo para o motivo.
- **Formato de saida:** OGG Opus 24 kbps, 16 kHz mono.
- **Integridade de audio (11/04/2026):** 2.440 de 2.440 requisicoes em todas as quatro configuracoes produziram arquivos de audio validos (verificado com `ffprobe`). Zero crashes, zero saidas corrompidas.
- **Datas dos testes:** 06/04/2026 (single-replica inicial), 11/04/2026 (verificacao multi-replica de quatro configuracoes)
