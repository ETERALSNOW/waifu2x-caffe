# Plan: PDF/EPUB/MOBI preprocessing for waifu2x-caffe

## Goals
- Add user-facing support for PDF, EPUB, and MOBI input while keeping the existing waifu2x super-resolution pipeline untouched.
- Treat these formats as containers: extract raster images, upscale them with the current image pipeline, and repackage the outputs back into the original container type.
- Keep the change modular so core image processing remains unchanged and optional dependencies are isolated.

## Current input handling touchpoints
- `waifu2x-caffe/Source.cpp` handles CLI parsing and dispatch. Folder inputs iterate images by extension and enqueue them for processing; single-file inputs go straight to the converter. There is no container-type branch today.
- `waifu2x-caffe-gui/MainDialog.cpp` mirrors CLI behavior for folder/file selection and passes the resulting image list to the processing thread.
- Output path auto-selection and input extension enumeration are centralized around the CLI `--input_extention_list` and GUI defaults.

## Proposed architecture
1. **Preprocessing layer (new module)**
   - Implement a container-aware preprocessor that runs *before* the current image queue is built. It should accept: `(input_path, work_root, opts)` and return `(image_list, cleanup_handle, repack_descriptor)`.
   - If `input_path` is a standard image or directory, fall back to existing behavior.
   - For PDF/EPUB/MOBI, create a temporary working directory under `work_root`, extract/convert images into subfolders grouped by container, and emit an ordered list of paths for waifu2x.
   - Expose the preprocessor via a thin interface so both CLI and GUI can call it without duplicating logic.

2. **Format-specific strategies**
   - **PDF**
     - Prefer extracting embedded raster images when available; otherwise render each page to a bitmap (300–400 DPI configurable) with a single dependency hook (e.g., Poppler or MuPDF). Record page order and original image names if present.
     - Output structure: `temp/<job>/pdf/pages/<page-index>/img_<seq>.png` and a manifest that maps each extracted file to either an embedded object or a rendered page.
     - Repacking: replace page images in a fresh PDF using a lightweight writer (e.g., pikepdf/Poppler-based Python helper) or re-render enhanced page bitmaps back to PDF pages. Keep page order and metadata.

   - **EPUB/MOBI**
     - Treat input as a zip-like container; extract images found in manifest/spine order. For MOBI, use `ebook-convert`/`kindlegen`-compatible tooling or `libmobi` wrapper to unpack; fall back to treating MOBI as AZW3/EPUB via `ebook-convert` if present.
     - Output structure: `temp/<job>/book/original/<relative-image-path>` with manifest JSON capturing the original internal path and the exported filename.
     - Repacking: copy the original container contents to a temp area and overwrite only the images enumerated in the manifest with their enhanced counterparts, preserving directory layout and other assets.

3. **Integration points**
   - Add a preprocessing dispatch step in the CLI flow immediately after input path resolution (before building the image vector). The dispatcher should decide whether to run the container preprocessor or the existing folder/file enumerator.
   - In the GUI, call the same dispatcher from the worker thread that currently scans input files. Preserve progress reporting by treating preprocessing/extraction and repacking as separate phases with progress callbacks.
   - Keep the core waifu2x image processing (model loading, batching, TTA, etc.) untouched by feeding it the returned `image_list`.

4. **Interface sketch (pseudocode)**
   ```cpp
   struct ContainerManifest {
       std::vector<std::wstring> extracted_images; // absolute paths fed to waifu2x
       std::function<void()> cleanup;              // deletes temp working set
       std::function<void(const std::vector<std::wstring>& processed)> repack; // consumes processed outputs
       std::wstring display_name;                  // for progress labels
   };

   ContainerManifest preprocess(const std::wstring& input_path,
                                const std::wstring& work_root,
                                const PreprocessOptions& opts);

   // CLI
   auto manifest = preprocess(input_path, work_root, opts);
   process_images(manifest.extracted_images, output_dir, ...);
   manifest.repack(collected_outputs);
   manifest.cleanup();
   ```

5. **Dependency and build implications**
   - To minimize C++ build impact, implement heavy container parsing in an auxiliary script (e.g., `tools/container_preprocess.py`) invoked by the preprocessor. Suggested third-party Python deps: `pymupdf` or `pdfplumber` (PDF), `pikepdf` (PDF writing), `beautifulsoup4`/`lxml` (EPUB), `libmobi` or `ebooklib` (MOBI). Package checks should be optional; when missing, emit a clear error suggesting installation.
   - Keep the C++ binary dependency-free: the preprocessor shells out to the Python helper and exchanges data via JSON manifests and temp directories. On Windows, ship the helper alongside the executable and document the Python/runtime requirement.

6. **Limitations and assumptions**
   - Vector PDFs are rasterized at a configurable DPI; non-image vector content will be flattened.
   - DRM-protected or encrypted EPUB/MOBI/PDF files are out of scope and should produce a clear error.
   - Only raster images are upscaled; audio/video or SVG assets are passed through unchanged.
   - For MOBI, quality depends on unpacking support from the chosen helper (e.g., `ebook-convert` availability).

7. **Next steps**
   - Implement `tools/container_preprocess.py` with subcommands for `pdf`, `epub`, `mobi`, emitting a manifest JSON (`extracted_images`, `repack_plan`).
   - Add a thin C++ wrapper that detects container types by extension, invokes the helper, and reuses existing image-processing code paths.
   - Extend CLI/GUI help text and documentation (README/README-EN) to describe the new formats, temp dir usage, and dependency requirements.
   - Add smoke tests that run the helper on small sample fixtures and verify manifests and repacked outputs round-trip.
