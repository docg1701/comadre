# CUMADRE — Guia de Implementacao

> **CUMADRE** = **Cu**madre **M**anda **A**udio **D**ireto, **R**apido e **E**ficiente

Servico self-hosted de text-to-speech com clonagem de voz, otimizado para respostas automaticas em portugues brasileiro. Integra-se a plataformas de atendimento ao cliente via n8n para converter respostas textuais de LLMs em mensagens de audio com voz humana clonada.

---

## O que e o KokoClone

KokoClone e uma solucao completa e autonoma de TTS com clonagem de voz. Ao instalar o KokoClone, voce recebe:

| Componente | Funcao | Vem como |
|---|---|---|
| **Kokoro-ONNX** (82M params) | Gera fala a partir de texto | dependencia pip |
| **Kanade** (120M params) | Converte a voz gerada para a voz clonada | dependencia pip (GitHub) |
| **Vocoder** (Vocos 24kHz) | Sintetiza audio final | incluso no Kanade |
| **Misaki** | Fonematizador (en, ja, zh; pt via espeak-ng) | dependencia pip |
| **Gradio UI** | Interface web para testes | dependencia pip |

Nao existe outro projeto para instalar. Nao precisa de Kokoro-FastAPI, nao precisa de nada separado. O `pip install -r requirements.txt` do KokoClone traz tudo.

### Como funciona internamente (cada chamada)

```
Texto → Kokoro TTS (gera fala com voz base) → Kanade (converte para voz clonada) → Audio WAV
```

Os dois passos acontecem em toda chamada. O audio de referencia do funcionario (3-10s WAV) e carregado e processado pelo Kanade a cada geracao. Nao existe perfil de voz persistente — e zero-shot puro.

### O que o KokoClone NAO tem

- **REST API** — so tem Gradio UI, CLI e Python API
- **Dockerfile** — nao existe no repositorio
- **Releases/versoes** — nenhuma release publicada no GitHub

Portanto, o trabalho de implementacao e:
1. Escrever um wrapper FastAPI fino (~80 linhas) em cima da Python API
2. Escrever um Dockerfile
3. Escrever um docker-compose.yml
4. Configurar o n8n para chamar o endpoint

---

## Recursos Estimados

### Disco

| Item | Tamanho |
|---|---|
| Kokoro ONNX (82M params) | ~300-400 MB |
| Kanade + Vocoder (120M params) | ~500 MB - 1 GB |
| PyTorch CPU + dependencias Python | ~1-1.5 GB |
| Modelos de voz (.bin) | ~50-100 MB |
| **Total** | **~2-3 GB** |

Modelos sao baixados automaticamente do HuggingFace no primeiro run. Nao e necessario baixar manualmente.

### RAM

| Item | Uso |
|---|---|
| Kokoro ONNX em memoria | ~400-600 MB |
| Kanade + Vocoder em memoria | ~600 MB - 1 GB |
| PyTorch runtime + buffers | ~300-500 MB |
| FastAPI + overhead | ~100 MB |
| **Total estimado** | **~1.5-2.5 GB** |

O KokoClone cacheia o modelo Kokoro por idioma (`self.kokoro_cache`), entao apos a primeira geracao em pt-BR, as subsequentes nao recarregam o modelo.

### CPU

Kokoro ONNX usa threads configuraveis. O Kanade usa PyTorch CPU. Para frases curtas de 15 palavras:

| Etapa | Tempo estimado (4 vCPU) |
|---|---|
| Kokoro TTS (gerar fala base) | ~200-500 ms |
| Kanade voice conversion | ~500 ms - 2 s |
| **Total por request** | **~1-3 s** |

**Throughput estimado: 20-60 req/min** em 4 vCPUs. Isso e uma estimativa — nao existem benchmarks publicados para KokoClone em CPU. O valor real precisa ser medido no VPS.

**Nota importante:** O throughput de 200-400 req/min mencionado no guia anterior era do Kokoro-FastAPI puro (sem Kanade). Com a etapa extra de voice conversion do KokoClone, o throughput e significativamente menor. Se 20-60 req/min for insuficiente para a demanda real, as opcoes sao:
- Rodar 2 workers (dobra throughput, dobra RAM para ~4-5 GB)
- Cachear respostas frequentes (reduz chamadas reais ao TTS)
- Adicionar GPU ao VPS

### Distribuicao de recursos no VPS (4 vCPU / 8 GB RAM)

| Servico | CPU | RAM |
|---|---|---|
| TTS Service (KokoClone + FastAPI) | 2-3 vCPUs | 2-3 GB |
| n8n | 0.5-1 vCPU | 0.5-1 GB |
| SO + overhead | 0.5 vCPU | 0.5 GB |
| **Total** | **~4 vCPUs** | **~3-4.5 GB** |
| **Livre** | — | **~3.5-5 GB** |

Sobra RAM confortavelmente. Se for adicionar Chatwoot+Postgres+Redis na Phase 4 (+1.5-2 GB), ainda cabe.

---

## Arquitetura

```
┌────────────────────────────────────────────────────────┐
│                  VPS (4 vCPU / 8 GB RAM)               │
│                                                         │
│  ┌──────────────┐     ┌──────────────────────────┐     │
│  │     n8n      │     │    TTS Service (FastAPI)  │     │
│  │              │────>│                           │     │
│  │  Workflows:  │     │  KokoClone engine:        │     │
│  │  - STT(Groq) │     │    Kokoro (TTS)           │     │
│  │  - LLM       │     │    + Kanade (voice conv.) │     │
│  │  - TTS call  │<────│                           │     │
│  │  - Telegram  │     │  POST /v1/audio/speech    │     │
│  │  - Chatwoot  │     │  GET  /health             │     │
│  └──────────────┘     └──────────────────────────┘     │
│                                                         │
│  voices/employee.wav   (arquivo unico, copiado 1x)     │
└────────────────────────────────────────────────────────┘
```

### Fluxo completo (audio do cliente → audio de resposta)

```
1. Cliente manda audio (WhatsApp/Telegram/etc)
2. n8n recebe via webhook/trigger
3. n8n detecta: e audio → faz download do arquivo
4. n8n envia audio para Groq Whisper (STT) → recebe texto
5. n8n envia texto para LLM → recebe resposta em texto
6. n8n envia POST /v1/audio/speech com o texto da resposta
7. TTS Service: Kokoro gera fala base → Kanade converte para voz clonada
8. TTS Service retorna audio WAV/OGG
9. n8n envia audio de volta ao cliente
```

---

## Implementacao

### Estrutura do projeto

```
kokoclone-service/
├── docker-compose.yml
├── tts-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── server.py              # FastAPI wrapper (~80 linhas)
│   └── voices/
│       └── employee.wav       # Audio de referencia (3-10s)
```

### requirements.txt

```
# TTS + Voice Cloning (KokoClone e suas dependencias)
torch --index-url https://download.pytorch.org/whl/cpu
torchaudio --index-url https://download.pytorch.org/whl/cpu
kokoro-onnx
misaki[en,ja,zh]
git+https://github.com/frothywater/kanade-tokenizer
soundfile
huggingface_hub
numpy

# API Server
fastapi
uvicorn[standard]
python-multipart
```

**Nota:** Esses requirements sao baseados no `requirements.txt` oficial do KokoClone [1]. Na hora do build, verificar se houve alteracoes no repositorio original.

### server.py

```python
"""
TTS Service: wrapper FastAPI sobre a Python API do KokoClone.
Unico endpoint relevante: POST /v1/audio/speech (OpenAI-compatible).
"""
import io
import os
import time
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tts")

VOICES_DIR = Path(os.getenv("VOICES_DIR", "/app/voices"))
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "employee")
PORT = int(os.getenv("PORT", "8880"))

engine = None  # KokoClone instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    # Import aqui para nao quebrar se dependencias faltarem
    from core.cloner import KokoClone

    log.info("Carregando KokoClone (Kokoro + Kanade)...")
    engine = KokoClone()

    # Aquecer: primeira geracao carrega modelos e e mais lenta
    ref = VOICES_DIR / f"{DEFAULT_VOICE}.wav"
    if ref.exists():
        log.info(f"Aquecendo com voz padrao: {ref}")
        engine.generate("Teste.", lang="pt", reference_audio=str(ref), output_path="/tmp/_warmup.wav")
        os.unlink("/tmp/_warmup.wav")
        log.info("Aquecimento concluido.")
    else:
        log.warning(f"Voz padrao nao encontrada em {ref}")

    yield
    log.info("Encerrando TTS Service.")


app = FastAPI(title="KokoClone TTS Service", lifespan=lifespan)


class SpeechRequest(BaseModel):
    model: str = "kokoclone"
    input: str
    voice: str = DEFAULT_VOICE
    response_format: str = "wav"


@app.get("/health")
def health():
    voices = [f.stem for f in VOICES_DIR.glob("*.wav")]
    return {"status": "ok", "engine": "kokoclone", "voices": voices}


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    if not req.input.strip():
        raise HTTPException(400, "Texto vazio")

    ref = VOICES_DIR / f"{req.voice}.wav"
    if not ref.exists():
        raise HTTPException(404, f"Voz '{req.voice}' nao encontrada em {VOICES_DIR}")

    out_path = f"/tmp/tts_{os.getpid()}_{time.time_ns()}.wav"
    t0 = time.perf_counter()

    try:
        engine.generate(
            text=req.input,
            lang="pt",
            reference_audio=str(ref),
            output_path=out_path,
        )
        elapsed = time.perf_counter() - t0
        data, sr = sf.read(out_path)
        duration = len(data) / sr
        log.info(f"Gerado {duration:.1f}s de audio em {elapsed:.2f}s (RTF {elapsed/duration:.2f})")

        buf = io.BytesIO()
        fmt = "OGG" if req.response_format == "ogg" else "WAV"
        subtype = "VORBIS" if fmt == "OGG" else None
        sf.write(buf, data, sr, format=fmt, subtype=subtype)
        buf.seek(0)

        media = "audio/ogg" if fmt == "OGG" else "audio/wav"
        return Response(content=buf.read(), media_type=media)
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, workers=1)
```

**Sobre o codigo:**
- `workers=1` porque KokoClone carrega modelos em memoria e compartilha `self.kokoro_cache`. Multiplos workers carregariam modelos duplicados.
- O aquecimento (`warmup`) no startup carrega todos os modelos na memoria e evita que a primeira requisicao real demore 10-30s.
- O `engine.generate()` e exatamente a API publica do KokoClone, conforme documentada no README e confirmada no codigo-fonte [1][2].
- O endpoint retorna WAV por padrao. Para Telegram voice notes, usar `response_format: ogg`.

### Dockerfile

```dockerfile
FROM python:3.12-slim

# espeak-ng para fonematizacao pt-BR + ffmpeg + libsndfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng libespeak-ng-dev ffmpeg libsndfile1 git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clonar KokoClone (pega core/, model/, voice/ etc.)
RUN git clone --depth 1 https://github.com/Ashish-Patnaik/kokoclone.git /tmp/kokoclone \
    && cp -r /tmp/kokoclone/core /app/core \
    && rm -rf /tmp/kokoclone

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Servidor
COPY server.py .

# Diretorio de vozes (montado como volume)
RUN mkdir -p /app/voices

ENV VOICES_DIR=/app/voices
ENV DEFAULT_VOICE=employee
ENV PORT=8880

EXPOSE 8880

# Modelos baixam automaticamente do HuggingFace no primeiro run
CMD ["python", "server.py"]
```

### docker-compose.yml

```yaml
services:
  tts:
    build: ./tts-service
    container_name: tts-service
    ports:
      - "8880:8880"
    volumes:
      - ./tts-service/voices:/app/voices    # audio de referencia
      - tts-models:/root/.cache/huggingface # cache de modelos
    environment:
      - DEFAULT_VOICE=employee
      - PORT=8880
      - PYTHONUNBUFFERED=1
    deploy:
      resources:
        limits:
          cpus: '3.0'
          memory: 4G
        reservations:
          memory: 2G
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8880/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s  # modelos demoram para baixar no primeiro run

  n8n:
    image: n8nio/n8n:latest
    container_name: n8n
    ports:
      - "5678:5678"
    volumes:
      - n8n-data:/home/node/.n8n
    environment:
      - N8N_HOST=0.0.0.0
      - WEBHOOK_URL=https://seu-dominio.com/
      - GENERIC_TIMEZONE=America/Sao_Paulo
    restart: unless-stopped

volumes:
  tts-models:
  n8n-data:
```

---

## Deploy

### 1. Preparar voz de referencia (DevOps, unica vez)

Gravar 3-10 segundos do funcionario falando naturalmente. Requisitos:
- Ambiente silencioso, sem eco
- Fala natural, nao lida de um script
- Formato WAV, 16kHz+ sample rate (24kHz ideal, e o sample rate do Kanade)
- Conteudo irrelevante — o que importa e o timbre, nao as palavras

```bash
# Salvar como employee.wav na pasta voices/
cp gravacao_funcionario.wav kokoclone-service/tts-service/voices/employee.wav
```

### 2. Build e deploy

```bash
cd kokoclone-service
docker compose up --build -d

# Acompanhar primeiro boot (download de modelos ~1-3 GB)
docker compose logs -f tts

# Quando aparecer "Aquecimento concluido." esta pronto
```

### 3. Testar

```bash
# Health check
curl http://localhost:8880/health

# Gerar audio em pt-BR
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Bom dia, sua solicitacao foi registrada com sucesso.","voice":"employee"}' \
  --output teste.wav

# Ouvir o audio e avaliar qualidade
```

### 4. Restart preventivo (memory leak do Kokoro)

```bash
# Cron no host: restart diario as 4h da manha
(crontab -l 2>/dev/null; echo "0 4 * * * docker restart tts-service") | crontab -
```

---

## Integracao n8n

### Phase 1: Chat basico (texto → audio)

Workflow n8n: `Chat Trigger → HTTP Request (TTS) → Respond to Chat`

**HTTP Request node:**

| Campo | Valor |
|---|---|
| Method | POST |
| URL | `http://tts-service:8880/v1/audio/speech` |
| Body Content Type | JSON |
| Response Format | File |

**Body (JSON):**
```json
{
  "input": "={{ $json.output }}",
  "voice": "employee",
  "response_format": "wav"
}
```

Funciona porque n8n e tts-service estao na mesma Docker network (mesmo docker-compose).

### Phase 2: Telegram (audio → audio)

```
[Telegram Trigger] → [Switch: tipo de mensagem]
     ├── texto → [LLM] → [TTS] → [Telegram: enviar audio]
     └── voice → [Download arquivo .oga]
                      → [Groq Whisper STT] → texto
                      → [LLM] → resposta em texto
                      → [TTS: POST /v1/audio/speech] → audio
                      → [Telegram: enviar audio]
```

**Enviar voice note no Telegram (nao arquivo de musica):**

O node Telegram do n8n so tem `sendAudio` (envia como musica). Para enviar como voice note, usar HTTP Request direto na Bot API [3]:

```
Method: POST
URL: https://api.telegram.org/bot{{ $credentials.telegramApi }}/sendVoice
Body: Form-Data / Multipart
  chat_id: {{ $json.message.chat.id }}
  voice: [binary do audio em formato OGG]
```

O audio DEVE ser OGG/Opus. Configurar o TTS para retornar `response_format: ogg`.

### Phase 3: Chatwoot + Human-in-the-Loop

**Setup:**
1. Chatwoot → Settings → Integrations → Webhooks
2. URL do webhook: `https://seu-dominio.com/webhook/chatwoot`
3. Evento: `message_created`

**Logica de pausa/retomada do bot:**

```
Webhook recebe mensagem do Chatwoot
    → Checar: conversa tem label "human"?
        SIM → Ignorar (humano respondendo)
        NAO → Processar com LLM + TTS → responder via API Chatwoot
```

O agente humano no dashboard do Chatwoot:
- **Pausar bot:** adicionar label `human` na conversa
- **Retomar bot:** remover label `human`
- **Corrigir:** apagar resposta do bot e enviar manualmente

Chatwoot adiciona ~1.5-2 GB de RAM (app + Postgres + Redis). O VPS de 8 GB ainda comporta (total ~6-6.5 GB).

---

## O que ainda precisa ser validado empiricamente

| Item | Como validar | Risco se falhar |
|---|---|---|
| Qualidade pt-BR do KokoClone | Gerar 20 frases de atendimento, ouvir | Baixo — espeak-ng pt-BR e funcional |
| Latencia real no VPS | Medir com `time curl ...` | Medio — se >3s por request, throughput cai |
| RAM real do container | `docker stats tts-service` | Baixo — estimativa de 2-3 GB e conservadora |
| Memory leak ao longo de horas | Monitorar RAM por 24h | Mitigado com restart diario |
| Formato OGG via soundfile | Testar `response_format: ogg` | Se falhar, converter com ffmpeg no server |

---

## Cronograma

| Fase | O que | Tempo |
|---|---|---|
| 1 | Build Docker + deploy TTS + testar pt-BR | Dia 1 |
| 2 | Workflow n8n: chat texto → audio | Dia 1 |
| 3 | Telegram bot: audio bidirecional | Dia 2 |
| 4 | Chatwoot + human-in-the-loop | Dia 3-4 |

---

## Referencias

[1] Ashish-Patnaik. "KokoClone: Voice Cloning, Now Inside Kokoro". GitHub. https://github.com/Ashish-Patnaik/kokoclone

[2] KokoClone source: `core/cloner.py`. https://github.com/Ashish-Patnaik/kokoclone/blob/main/core/cloner.py

[3] n8n Community. "Add Telegram sendVoice". https://community.n8n.io/t/add-telegram-sendvoice/69712

[4] frothywater. "Kanade Tokenizer". GitHub. https://github.com/frothywater/kanade-tokenizer

[5] n8n. "Telegram node documentation". https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.telegram/

[6] n8n. "Build a multichannel customer support AI assistant with Chatwoot". https://n8n.io/workflows/8260

[7] n8n. "Human-in-the-loop for AI tool calls". https://docs.n8n.io/advanced-ai/human-in-the-loop-tools/
