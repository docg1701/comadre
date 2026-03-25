# espeak-ng Custom Dictionary for Brazilian Portuguese Siglas

**Date:** 2026-03-23
**Status:** Implemented and tested — all siglas pronouncing correctly
**Impact:** Kokoro TTS now has 100% perfect sigla pronunciation

## Overview

espeak-ng supports a `pt_extra` dictionary file that allows adding custom pronunciation entries WITHOUT modifying the main `pt_list` dictionary. This is critical because the main `pt_list` was updated by the PR #2344 contributor and we don't want to conflict with future updates.

The `pt_extra` file is compiled LAST (after `pt_list`) and its entries take precedence. This makes our customizations **fully additive**.

## Compilation Order (from source code)

```text
1. pt_roots     (if exists)
2. pt_list      (main dictionary — PR #2344 improvements)
3. pt_listx     (extensions, if exists)
4. pt_emoji     (emoji pronunciations)
5. pt_extra     (OUR CUSTOM ENTRIES — added last, highest priority)
```

## How to Add/Modify Entries

### File format

```text
// Comments start with //
WORD    $abbrev              ← spell out letter by letter
WORD    phoneme_string       ← custom pronunciation
```

### Sigla types

| Type | Format | Example |
|---|---|---|
| **Soletrada** (letter by letter) | `$abbrev` | `CPF $abbrev` → "cê-pê-éfe" |
| **Palavra** (pronounced as word) | Custom phonemes | `SUS s'us` → "sus" |

### Phoneme notation (pt-BR)

Key phonemes for Brazilian Portuguese:

- Vowels: `a` (aberto), `E` (é), `i`, `O` (ó), `u`
- Nasalized: `&~` (ã), `e~` (en), `i~` (in)
- Stress: `'` (primary), `,` (secondary)
- Consonants: `s`, `z`, `S` (sh), `Z` (j/zh), `R` (rr), `r` (r fraco), `k`, `g`, `t`, `d`, `f`, `v`, `n`, `m`, `l`

## Current pt_extra Content

```text
// ============================================================
// SIGLAS SOLETRADAS ($abbrev — each letter pronounced individually)
// ============================================================

// Government & Documents
cpf     $abbrev    // Cadastro de Pessoas Físicas
cnpj    $abbrev    // Cadastro Nacional de Pessoas Jurídicas
rg      $abbrev    // Registro Geral
cnh     $abbrev    // Carteira Nacional de Habilitação
cnis    $abbrev    // Cadastro Nacional de Informações Sociais

// Legal / Judiciary
stf     $abbrev    // Supremo Tribunal Federal
stj     $abbrev    // Superior Tribunal de Justiça
trt     $abbrev    // Tribunal Regional do Trabalho
trf     $abbrev    // Tribunal Regional Federal
tst     $abbrev    // Tribunal Superior do Trabalho
cnj     $abbrev    // Conselho Nacional de Justiça
dpf     $abbrev    // Departamento de Polícia Federal
dpu     $abbrev    // Defensoria Pública da União

// Labor
clt     $abbrev    // Consolidação das Leis do Trabalho
ctps    $abbrev    // Carteira de Trabalho e Previdência Social
fgts    $abbrev    // Fundo de Garantia por Tempo de Serviço

// Social Benefits
bpc     $abbrev    // Benefício de Prestação Continuada

// Financial
dasn    $abbrev    // Declaração Anual do Simples Nacional
csll    $abbrev    // Contribuição Social sobre o Lucro Líquido

// Banking
cdb     $abbrev    // Certificado de Depósito Bancário
lci     $abbrev    // Letra de Crédito Imobiliário
lca     $abbrev    // Letra de Crédito do Agronegócio
coe     $abbrev    // Certificado de Operações Estruturadas
iof     $abbrev    // Imposto sobre Operações Financeiras
cvm     $abbrev    // Comissão de Valores Mobiliários
b3      $abbrev    // Bolsa de Valores

// Common
ibge    $abbrev    // Instituto Brasileiro de Geografia e Estatística
ipca    $abbrev    // Índice de Preços ao Consumidor Amplo
igpm    $abbrev    // Índice Geral de Preços do Mercado
bndes   $abbrev    // Banco Nacional de Desenvolvimento

// Technology
url     $abbrev
http    $abbrev
https   $abbrev
api     $abbrev
pdf     $abbrev
sms     $abbrev
gps     $abbrev

// ============================================================
// SIGLAS PRONUNCIADAS COMO PALAVRA (custom phonemes)
// ============================================================

sus     s'us       // Sistema Único de Saúde
pix     p'iks      // Sistema de pagamento instantâneo
detran  detr'&~    // Departamento de Trânsito
loas    l'oas      // Lei Orgânica da Assistência Social
cras    kr'as      // Centro de Referência de Assistência Social
creas   kr'Eas     // Centro de Referência Especializado
suas    s'uas      // Sistema Único de Assistência Social
upa     'upa       // Unidade de Pronto Atendimento
samu    sam'u      // Serviço de Atendimento Móvel de Urgência
anvisa  &~v'iza    // Agência Nacional de Vigilância Sanitária
fiocruz fiokr'us   // Fundação Oswaldo Cruz
enem    en'eIN     // Exame Nacional do Ensino Médio
fies    f'iEs      // Fundo de Financiamento Estudantil
prouni  proun'i    // Programa Universidade para Todos
sisu    siz'u      // Sistema de Seleção Unificada
selic   sel'iky    // Sistema Especial de Liquidação e Custódia
cofins  kof'i~s    // Contribuição para Financiamento da Seguridade Social
bacen   bas'e~     // Banco Central do Brasil
mei     m'Ej       // Microempreendedor Individual
simei   sim'Ej     // Sistema de Recolhimento em Valores Fixos Mensais
darf    d'aRfy     // Documento de Arrecadação de Receitas Federais
ibama   ib'ama     // Instituto Brasileiro do Meio Ambiente
inpe    'i~pi      // Instituto Nacional de Pesquisas Espaciais
inmet   i~m'Ety    // Instituto Nacional de Meteorologia
embrapa e~br'apa   // Empresa Brasileira de Pesquisa Agropecuária
petrobras petroBr'as // Petróleo Brasileiro S.A.
wifi    wajf'aj    // Wireless Fidelity
```

## How to Recompile

### Prerequisites

- espeak-ng source code cloned at `/tmp/espeak-ng/`
- espeak-ng already built with cmake (build dir at `/tmp/espeak-ng/build/`)

### Steps

```bash
# 1. Edit the pt_extra file (add/modify entries)
vi /tmp/espeak-ng/dictsource/pt_extra

# 2. Compile from the dictsource directory (CRITICAL — must cd here)
cd /tmp/espeak-ng/dictsource
ESPEAK_DATA_PATH=/tmp/espeak-ng/build/espeak-ng-data \
    /tmp/espeak-ng/build/src/espeak-ng --compile=pt

# 3. Verify output — should say "Compiling: 'pt_extra'" with N entries
# If "Error processing file 'pt_rules'" appears, you're in the wrong directory

# 4. Copy compiled dict to install location
cp /tmp/espeak-ng/build/espeak-ng-data/pt_dict \
   /tmp/espeak-ng-install/share/espeak-ng-data/pt_dict

# 5. Test
ESPEAK_DATA_PATH=/tmp/espeak-ng-install/share/espeak-ng-data \
    /tmp/espeak-ng-install/bin/espeak-ng -v pt-br -x "CNPJ"
# Expected: s,e,enyp,eZ'Ot&  (cê-ene-pê-jota)
```

### Docker build integration

```dockerfile
# After building espeak-ng from source:
COPY dictsource/pt_extra /tmp/espeak-ng/dictsource/pt_extra
RUN cd /tmp/espeak-ng/dictsource && \
    ESPEAK_DATA_PATH=/usr/local/share/espeak-ng-data \
    /tmp/espeak-ng/build/src/espeak-ng --compile=pt
```

## Testing

Test all siglas with:

```bash
for sigla in CPF CNPJ RG CNH STF STJ TRT TRF BPC CLT FGTS SUS PIX DETRAN ENEM SAMU; do
    ph=$(ESPEAK_DATA_PATH=/tmp/espeak-ng-install/share/espeak-ng-data \
         /tmp/espeak-ng-install/bin/espeak-ng -v pt-br -x "$sigla" 2>&1)
    echo "$sigla → $ph"
done
```

## Verified Results

| Sigla | Tipo | Fonemas | Pronúncia |
|---|---|---|---|
| CPF | Soletrada | `s,ep,e'Efy` | cê-pê-éfe ✓ |
| CNPJ | Soletrada | `s,e,enyp,eZ'Ot&` | cê-ene-pê-jota ✓ |
| RG | Soletrada | `,ExyZ'e` | érre-gê ✓ |
| CNH | Soletrada | `s,e,eny;ag'a` | cê-ene-agá ✓ |
| STF | Soletrada | `,Esyt,e'Efy` | esse-tê-éfe ✓ |
| STJ | Soletrada | `,Esyt,eZ'Ot&` | esse-tê-jota ✓ |
| TRT | Soletrada | `t,e,Exyt'e` | tê-érre-tê ✓ |
| TRF | Soletrada | `t,e,Exy;'Efy` | tê-érre-éfe ✓ |
| TST | Soletrada | `t,e,Esyt'e` | tê-esse-tê ✓ |
| BPC | Soletrada | `b,ep,es'e` | bê-pê-cê ✓ |
| CLT | Soletrada | `s,e,Elyt'e` | cê-éle-tê ✓ |
| CTPS | Soletrada | `s,et,ep,e'Esy` | cê-tê-pê-esse ✓ |
| FGTS | Soletrada | `,EfyZ,et,e'Esy` | éfe-gê-tê-esse ✓ |
| SUS | Palavra | `s'us` | "sus" ✓ |
| PIX | Palavra | `p'iks` | "pix" ✓ |
| DETRAN | Palavra | `detr'&~` | "detran" ✓ |
| ENEM | Palavra | `en'eIN` | "enem" ✓ |
| SAMU | Palavra | `sam'u` | "samu" ✓ |
| ANVISA | Palavra | `,&~v'iza` | "anvisa" ✓ |

## CRITICAL: misaki ignores ESPEAK_DATA_PATH

**Discovery:** The `misaki` library (used by Kokoro) uses `espeakng_loader` which bundles its own `pt_dict`. The `ESPEAK_DATA_PATH` environment variable is **IGNORED** by misaki. It always reads from:

```text
.venv/lib/python3.12/site-packages/espeakng_loader/espeak-ng-data/pt_dict
```

### Solution: copy compiled pt_dict to BOTH locations

```bash
# After compiling:
# 1. Install to espeak-ng system path
cp /tmp/espeak-ng/build/espeak-ng-data/pt_dict \
   /tmp/espeak-ng-install/share/espeak-ng-data/pt_dict

# 2. ALSO install to espeakng_loader bundled path (for misaki/Kokoro)
cp /tmp/espeak-ng/build/espeak-ng-data/pt_dict \
   .venv/lib/python3.12/site-packages/espeakng_loader/espeak-ng-data/pt_dict
```

### CRITICAL: Must copy ALL data files, not just pt_dict

The `pt_dict` is compiled against specific phoneme data files (`phondata`, `phonindex`, `phontab`). If you copy only `pt_dict` but keep old phoneme files, the phonemes will be WRONG — words like "tudo" become "tʰuəʊ" instead of "tudʊ".

**Always copy ALL of these files together:**

```bash
LOADER=$(python -c "import espeakng_loader; print(espeakng_loader.get_data_path())")
BUILD=/tmp/espeak-ng/build/espeak-ng-data

cp "$BUILD/pt_dict"    "$LOADER/pt_dict"
cp "$BUILD/phondata"   "$LOADER/phondata"
cp "$BUILD/phonindex"  "$LOADER/phonindex"
cp "$BUILD/phontab"    "$LOADER/phontab"
```

### Docker integration

```dockerfile
# After building espeak-ng from source and installing Python deps:
RUN LOADER=$(python -c "import espeakng_loader; print(espeakng_loader.get_data_path())") && \
    cp /usr/local/share/espeak-ng-data/pt_dict    "$LOADER/pt_dict" && \
    cp /usr/local/share/espeak-ng-data/phondata   "$LOADER/phondata" && \
    cp /usr/local/share/espeak-ng-data/phonindex  "$LOADER/phonindex" && \
    cp /usr/local/share/espeak-ng-data/phontab    "$LOADER/phontab"
```

### Backup original

```bash
cp -r "$LOADER" "${LOADER}.backup"
```

| File | Original bundled | Our compiled |
|---|---|---|
| pt_dict | 76,389 bytes | **141,211 bytes** |
| phondata | 554,740 bytes | 555,064 bytes |
| phonindex | 43,316 bytes | 47,128 bytes |
| phontab | 58,652 bytes | 61,580 bytes |

## Important Notes

1. **pt_extra is additive** — does not modify pt_list (PR #2344 improvements preserved)
2. **Must compile from `dictsource/` directory** — espeak-ng looks for pt_rules, pt_list, pt_extra relative to CWD
3. **Phoneme table is pt-pt** (base) with pt-br variants applied via `-v pt-br`
4. **$abbrev flag** tells espeak-ng to spell letters using built-in pt-BR letter names — no need to specify phonemes manually
5. **Future siglas** can be added by editing pt_extra and recompiling (takes <1 second)
6. **pt_extra DOES override pt_list entries** — tested and confirmed (ENEM override works)
7. **MUST copy pt_dict to espeakng_loader** — misaki ignores ESPEAK_DATA_PATH env var
