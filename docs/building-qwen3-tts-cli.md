# Building qwen3-tts-cli from Source

## Overview

`qwen3-tts-cli` is the C++ inference binary for the Qwen3-TTS engine. It is built from the upstream `predict-woo/qwen3-tts.cpp` project with a custom seed patch that adds `--seed N` for reproducible audio generation.

The compiled binary lives at `deploy/bin/qwen3-tts-cli` and is copied into the Docker image during build (`Dockerfile:66`).

## When You Need to Rebuild

- Fresh repository clone (binary is tracked in git but was missing historically)
- Upstream `predict-woo/qwen3-tts.cpp` has a new release you want to pick up
- The seed patch needs updating after upstream changes

## Source Information

| Item | Value |
|------|-------|
| Upstream repo | `https://github.com/predict-woo/qwen3-tts.cpp` |
| Upstream commit (last verified) | `7a762e2` (2026-03-24) |
| ggml submodule commit | `5cecdad692d868e28dbd2f7c468504770108f30c` |
| Seed patch | `docs/qwen3-tts-cpp-seed-patch.diff` |
| Output binary | `deploy/bin/qwen3-tts-cli` |

## Build Dependencies

- `cmake` >= 3.14
- `g++` with C++17 support (GCC 13+ tested)
- `make`
- `git`

On Ubuntu/Debian:

```bash
sudo apt-get install cmake g++ make git
```

## Step-by-Step Build

All steps run from the project root (`~/cumadre` or wherever the repo is cloned).

### 1. Clone the upstream source INSIDE the project

**CRITICAL: Never use /tmp or any directory outside the project.**

```bash
git clone https://github.com/predict-woo/qwen3-tts.cpp.git tmp/qwen3-tts.cpp
```

### 2. Initialize the ggml submodule

The project depends on `ggml` (the tensor library from ggml-org). It is a git submodule that must be fetched separately.

```bash
cd tmp/qwen3-tts.cpp
git submodule update --init --recursive
```

### 3. Build the ggml library FIRST

The upstream CMakeLists.txt expects pre-built ggml static libraries at `ggml/build/src/`. You must build ggml before building qwen3-tts.

```bash
cd ggml
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_SHARED_LIBS=OFF
cmake --build . -j$(nproc)
cd ../..
```

This produces static archives in `ggml/build/src/`:
- `libggml.a`
- `libggml-base.a`
- `libggml-cpu.a`

**Why PIC and no shared libs:** The ggml static libs are linked into the qwen3-tts static libraries, which are then linked into the final executable. Without `-DCMAKE_POSITION_INDEPENDENT_CODE=ON`, the shared library build (which we don't need but CMake tries to build) will fail with relocation errors.

### 4. Apply the seed patch

The patch modifies 5 files: 4 source files (seed feature) + CMakeLists.txt (OpenMP linking fix).

```bash
git apply ../../docs/qwen3-tts-cpp-seed-patch.diff
```

**If the patch fails to apply** (upstream has changed), you must apply the changes manually. The patch modifies these files:

1. **`CMakeLists.txt`** — Adds `find_package(OpenMP)` and links `OpenMP::OpenMP_CXX` to the `qwen3-tts-cli` target. Without this, linking fails with undefined references to `GOMP_parallel`, `omp_get_thread_num`, etc., because ggml is built with OpenMP support but the upstream CMakeLists does not propagate it to the CLI target.

2. **`src/main.cpp`** — Adds `--seed <n>` to the help text (after `--repetition-penalty`) and adds CLI argument parsing for `--seed` that sets `params.seed` via `std::stoll`.

3. **`src/qwen3_tts.h`** — Adds `int64_t seed = -1;` field to the `tts_params` struct (after `language_id`). Default -1 means random.

4. **`src/qwen3_tts.cpp`** — In `synthesize_internal()`, after `transformer_.clear_kv_cache()` and before the `speech_codes` generation, adds:
   ```cpp
   if (params.seed >= 0) {
       transformer_.seed_rng(params.seed);
   }
   ```

5. **`src/tts_transformer.h`** — Adds a public method to the `TTSTransformer` class (after `get_error()`):
   ```cpp
   void seed_rng(int64_t seed) { rng_.seed(static_cast<uint32_t>(seed)); }
   ```
   This works because the class has a private `std::mt19937 rng_` member.

After manual application, regenerate the patch:
```bash
git diff > ../../docs/qwen3-tts-cpp-seed-patch.diff
```

### 5. Build qwen3-tts-cli

```bash
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --target qwen3-tts-cli -j$(nproc)
```

**Use `--target qwen3-tts-cli`** to skip the shared library (`libqwen3tts.so`) which fails to build due to PIC/relocation issues. The shared library is not needed — only the CLI binary matters.

The binary will be at `build/qwen3-tts-cli`.

### 7. Copy the binary to deploy/bin/

```bash
cd ../..  # back to project root
cp tmp/qwen3-tts.cpp/build/qwen3-tts-cli deploy/bin/qwen3-tts-cli
chmod +x deploy/bin/qwen3-tts-cli
```

### 8. Verify

```bash
# Check it's an ELF x86-64 binary
file deploy/bin/qwen3-tts-cli

# Check the --seed flag is present
deploy/bin/qwen3-tts-cli --help 2>&1 | grep seed

# Check shared library dependencies (all should be standard system libs)
ldd deploy/bin/qwen3-tts-cli
```

Expected `ldd` output — only standard system libraries:
```
libgomp.so.1    (OpenMP runtime)
libstdc++.so.6  (C++ standard library)
libm.so.6       (math library)
libgcc_s.so.1   (GCC runtime)
libc.so.6       (C library)
```

All of these are available in the Docker `python:3.12-slim` base image.

### 9. Clean up the build source

```bash
rm -rf tmp/qwen3-tts.cpp
```

## Quick Reference (Copy-Paste)

Complete build from a clean state:

```bash
# Clone + submodules
git clone https://github.com/predict-woo/qwen3-tts.cpp.git tmp/qwen3-tts.cpp
cd tmp/qwen3-tts.cpp
git submodule update --init --recursive

# Build ggml (static)
cd ggml && mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DBUILD_SHARED_LIBS=OFF
cmake --build . -j$(nproc)
cd ../..

# Apply seed patch (includes source changes + CMakeLists OpenMP fix)
git apply ../../docs/qwen3-tts-cpp-seed-patch.diff

# Build CLI only
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --target qwen3-tts-cli -j$(nproc)

# Deploy
cp qwen3-tts-cli ../../../deploy/bin/qwen3-tts-cli
chmod +x ../../../deploy/bin/qwen3-tts-cli
cd ../../..

# Verify
deploy/bin/qwen3-tts-cli --help 2>&1 | grep seed

# Clean up
rm -rf tmp/qwen3-tts.cpp
```

## Known Issues and Pitfalls

1. **ggml must be built separately first.** The upstream CMakeLists.txt expects pre-built static archives at `ggml/build/src/`. If you skip this step, compilation succeeds but linking fails with "cannot find -lggml".

2. **OpenMP linking is missing from upstream CMakeLists.txt.** The ggml library uses OpenMP for multi-threaded inference. The seed patch includes the fix for this. If applying manually, you must add `find_package(OpenMP)` and link `OpenMP::OpenMP_CXX` to the CLI target, otherwise you get undefined reference errors for `GOMP_parallel`, `GOMP_barrier`, `omp_get_thread_num`, `omp_get_num_threads`.

3. **The shared library build (`libqwen3tts.so`) will fail.** This is expected — it has PIC/relocation issues. Use `--target qwen3-tts-cli` to skip it. Only the static CLI binary is needed.

4. **The seed patch may not apply cleanly on newer upstream versions.** If `git apply` fails, apply the 4 changes manually (see step 4 above) and regenerate the patch with `git diff`.

5. **Never build in /tmp.** Use `tmp/` inside the project. System /tmp gets cleaned and you lose everything.

6. **The binary is ~1.7 MB, not 600 KB.** Earlier documentation referenced a smaller size from before ggml was integrated as a submodule. The current size with ggml linked in is normal.

7. **The binary is dynamically linked to standard system libs** (libc, libstdc++, libgomp, libm). These are all present in the Docker `python:3.12-slim` base image. Fully static linking is not needed.
