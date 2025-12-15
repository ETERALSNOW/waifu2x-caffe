# Container Super-Resolution helper (MVP)

This Python helper preprocesses container formats (PDF/EPUB/MOBI) so they can be fed into the existing `waifu2x-caffe` executable without modifying the C++ core.

## Usage

```
python -m container_sr --input <path> --output <path> --waifu2x <path_to_waifu2x.exe> [--dpi 300] [--tmp <dir>] [--waifu2x-args <extra waifu2x args>]
```

- Input detection is by extension: `.pdf`, `.epub`, `.mobi`, or normal image files/directories.
- For plain images or folders, the tool simply delegates to `waifu2x-caffe` with the provided arguments.

### Windows example

```
python -m container_sr --input book.epub --output book_hd.epub --waifu2x C:\path\to\waifu2x-caffe.exe --waifu2x-args -m noise_scale -n 3 -s 2
```

## Behavior by format

- **EPUB**: Extracts the archive, finds common image files (`png/jpg/jpeg/webp/avif`), upscales them, and re-zips while preserving structure.
- **MOBI**: Attempts to treat the file as a zip-like container. If that fails, the tool exits with guidance to convert to EPUB (e.g., `ebook-convert`) and retry.
- **PDF (render-based MVP)**: Renders each page to PNG at the specified DPI, upscales the rendered pages, and rebuilds a PDF from the enhanced images.

## Dependencies

Install the Python dependencies into your environment:

```
pip install pillow pdf2image
```

For PDF rendering, `pdf2image` requires [Poppler](https://github.com/oschwartz10612/poppler-windows/releases/) on Windows (add `bin` to PATH) or `poppler-utils` on Linux.

## Notes and assumptions

- The waifu2x processing parameters (noise/scale/etc.) are passed via `--waifu2x-args` directly to the waifu2x-caffe executable.
- Temporary directories are cleaned up automatically unless you pass `--tmp`.
- MOBI support is best-effort; if the container is not zip-compatible, convert to EPUB first.

## Manual test checklist

1. **EPUB round-trip**: run with a sample `.epub`; verify the output EPUB opens and images are enhanced while HTML/CSS remain unchanged.
2. **PDF round-trip**: run on a short PDF; confirm page order is preserved and the output PDF contains processed pages.
3. **MOBI failure path**: try a MOBI that is not zip-compatible; confirm the tool exits cleanly with the conversion guidance.
4. **Image passthrough**: run with a single image or folder; ensure the wrapper simply calls waifu2x and writes outputs.
