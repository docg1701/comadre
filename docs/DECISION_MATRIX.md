# Decision Matrix: Self-Hosted Voice Cloning TTS

## Scoring Criteria (0-10 scale)

| Criterion | Weight | Description |
|---|---|---|
| Voice Cloning | 20% | Zero-shot from short audio, ease of use |
| pt-BR Quality | 20% | Brazilian Portuguese pronunciation, naturalness |
| CPU Performance | 20% | Throughput on 4 vCPU/8GB, RTF |
| Self-Hosted/License | 15% | Open-source, commercial license, no hidden fees |
| Docker/Deploy | 10% | Docker Compose, Ansible-ready, ease of setup |
| n8n Integration | 10% | OpenAI-compatible API, existing templates |
| Active Maintenance | 5% | Recent commits, community, not abandoned |

## Weighted Scores

| Project | Clone | pt-BR | CPU | License | Docker | n8n | Active | **TOTAL** |
|---|---|---|---|---|---|---|---|---|
| **Kokoro + KokoClone** | 6 | 4 | 10 | 10 | 9 | 10 | 9 | **7.45** |
| **Chatterbox Multi** | 9 | 8 | 2 | 10 | 8 | 8 | 9 | **7.05** |
| **XTTS v2 (Idiap)** | 9 | 7 | 3 | 3* | 7 | 7 | 7 | **5.80** |
| **Pocket TTS** | 8 | 0 | 10 | 10 | 8 | 6 | 8 | **5.70** |
| **Fish Speech S2** | 9 | 9 | 0 | 6 | 8 | 5 | 10 | **5.55** |
| **Piper** | 1 | 5 | 10 | 9 | 9 | 6 | 6 | **5.45** |
| **F5-TTS** | 9 | 5 | 0 | 10 | 7 | 3 | 9 | **5.25** |
| **GPT-SoVITS** | 10 | 0 | 2 | 10 | 6 | 3 | 9 | **4.65** |
| **Qwen3-TTS** | 8 | 7 | 1 | 10 | 3 | 3 | 9 | **5.30** |

*XTTS v2 scores 3/10 on license because CPML prohibits commercial use and no license can be purchased.

## Winner by Constraint Set

| If you have... | Best Choice | Score |
|---|---|---|
| CPU only (4vCPU/8GB) | **Kokoro + KokoClone** | 7.45 |
| GPU available (~$40/mo) | **Chatterbox Multilingual** | 9.25* |
| No pt-BR requirement | **Pocket TTS** | 8.50* |
| Must clone voice easily | **Chatterbox Multi (GPU)** | 9.25* |

*Recalculated with GPU removing CPU constraint penalty.

## Recommendation Flow

```
Start
  │
  ├─ Can you add GPU ($30-50/mo)?
  │   ├─ YES → Chatterbox Multilingual + Chatterbox-TTS-Server
  │   │        MIT license, 23 languages, voice cloning, OpenAI API
  │   │
  │   └─ NO → Test Kokoro + KokoClone pt-BR quality
  │       ├─ Quality OK → Deploy Kokoro-FastAPI
  │       │                n8n template exists, 200+ req/min
  │       │
  │       └─ Quality BAD → Consider:
  │           ├─ XTTS v2 (if non-commercial use) → 2-5 req/min
  │           ├─ Wait for Pocket TTS pt-BR support
  │           └─ Revisit GPU option
  │
  └─ END
```
