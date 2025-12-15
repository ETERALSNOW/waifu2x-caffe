import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, List, Sequence

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".avif"}


def debug(msg: str) -> None:
    print(f"[container_sr] {msg}")


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def run_subprocess(command: Sequence[str]) -> None:
    debug("Running: " + " ".join(command))
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{exc}") from exc


def detect_input_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".pdf"}:
        return "pdf"
    if ext in {".epub"}:
        return "epub"
    if ext in {".mobi"}:
        return "mobi"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if path.is_dir():
        return "image"
    return "unknown"


def waifu2x_file(input_path: Path, output_path: Path, waifu2x: Path, waifu2x_args: Sequence[str]) -> None:
    ensure_directory(output_path.parent)
    command: List[str] = [str(waifu2x), "-i", str(input_path), "-o", str(output_path)]
    command.extend(waifu2x_args)
    run_subprocess(command)


def waifu2x_folder(input_dir: Path, output_dir: Path, waifu2x: Path, waifu2x_args: Sequence[str]) -> None:
    ensure_directory(output_dir)
    command: List[str] = [str(waifu2x), "-i", str(input_dir), "-o", str(output_dir)]
    command.extend(waifu2x_args)
    run_subprocess(command)


def iter_images(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file():
            yield path


def process_epub(epub_path: Path, output_path: Path, waifu2x: Path, tmp_dir: Path, waifu2x_args: Sequence[str]) -> None:
    working_dir = tmp_dir / "epub_extract"
    if working_dir.exists():
        shutil.rmtree(working_dir)
    ensure_directory(working_dir)

    with zipfile.ZipFile(epub_path, "r") as zf:
        zf.extractall(working_dir)
    debug(f"Extracted EPUB to {working_dir}")

    for img_path in iter_images(working_dir):
        rel = img_path.relative_to(working_dir)
        processed_path = working_dir / rel
        waifu2x_file(img_path, processed_path, waifu2x, waifu2x_args)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in working_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(working_dir)
                zf.write(file_path, arcname)
    debug(f"Wrote enhanced EPUB to {output_path}")


def process_mobi(mobi_path: Path, output_path: Path, waifu2x: Path, tmp_dir: Path, waifu2x_args: Sequence[str]) -> None:
    working_dir = tmp_dir / "mobi_extract"
    if working_dir.exists():
        shutil.rmtree(working_dir)
    ensure_directory(working_dir)

    try:
        with zipfile.ZipFile(mobi_path, "r") as zf:
            zf.extractall(working_dir)
        debug("Treated MOBI as zip container; extracted successfully")
    except zipfile.BadZipFile:
        msg = (
            "MOBI container not recognized as zip. "
            "Please convert to EPUB (e.g., using ebook-convert) and rerun."
        )
        raise RuntimeError(msg)

    for img_path in iter_images(working_dir):
        rel = img_path.relative_to(working_dir)
        processed_path = working_dir / rel
        waifu2x_file(img_path, processed_path, waifu2x, waifu2x_args)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in working_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(working_dir)
                zf.write(file_path, arcname)
    debug(f"Wrote enhanced MOBI archive to {output_path}")


def process_pdf(pdf_path: Path, output_path: Path, waifu2x: Path, tmp_dir: Path, waifu2x_args: Sequence[str], dpi: int) -> None:
    try:
        from pdf2image import convert_from_path
    except ImportError as exc:
        raise RuntimeError("pdf2image is required for PDF processing. Install via 'pip install pdf2image'.") from exc

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for PDF rebuilding. Install via 'pip install pillow'.") from exc

    page_dir = tmp_dir / "pdf_pages"
    processed_dir = tmp_dir / "pdf_processed"
    for d in (page_dir, processed_dir):
        if d.exists():
            shutil.rmtree(d)
        ensure_directory(d)

    debug(f"Rendering PDF pages at {dpi} DPI")
    pages = convert_from_path(str(pdf_path), dpi=dpi)
    page_files: List[Path] = []
    for idx, page in enumerate(pages, start=1):
        page_path = page_dir / f"page_{idx:04d}.png"
        page.save(page_path, "PNG")
        page_files.append(page_path)

    for page_path in page_files:
        processed_path = processed_dir / page_path.name
        waifu2x_file(page_path, processed_path, waifu2x, waifu2x_args)

    processed_images = []
    for page_path in sorted(processed_dir.glob("*.png")):
        img = Image.open(page_path).convert("RGB")
        processed_images.append(img)

    if not processed_images:
        raise RuntimeError("No pages rendered from PDF; cannot build output.")

    first, *rest = processed_images
    debug("Rebuilding PDF from enhanced images")
    first.save(output_path, save_all=True, append_images=rest)


def passthrough_image(input_path: Path, output_path: Path, waifu2x: Path, waifu2x_args: Sequence[str]) -> None:
    if input_path.is_dir():
        waifu2x_folder(input_path, output_path, waifu2x, waifu2x_args)
    else:
        waifu2x_file(input_path, output_path, waifu2x, waifu2x_args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Container-aware super-resolution wrapper for waifu2x-caffe")
    parser.add_argument("--input", required=True, help="Input file or directory (image/pdf/epub/mobi)")
    parser.add_argument("--output", required=True, help="Output path")
    parser.add_argument("--waifu2x", required=True, help="Path to waifu2x-caffe executable")
    parser.add_argument("--dpi", type=int, default=300, help="PDF render DPI (default: 300)")
    parser.add_argument("--tmp", dest="tmp_dir", help="Temporary working directory")
    parser.add_argument("--waifu2x-args", nargs=argparse.REMAINDER, default=[], help="Additional args passed to waifu2x-caffe")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output)
    waifu2x_path = Path(args.waifu2x)
    waifu2x_args: Sequence[str] = args.waifu2x_args

    if not waifu2x_path.exists():
        parser.error("--waifu2x executable not found")

    if args.tmp_dir:
        tmp_dir = Path(args.tmp_dir)
        ensure_directory(tmp_dir)
    else:
        tmp_dir = Path(tempfile.mkdtemp(prefix="container_sr_"))

    try:
        kind = detect_input_type(input_path)
        debug(f"Detected input type: {kind}")
        if kind == "epub":
            process_epub(input_path, output_path, waifu2x_path, tmp_dir, waifu2x_args)
        elif kind == "mobi":
            process_mobi(input_path, output_path, waifu2x_path, tmp_dir, waifu2x_args)
        elif kind == "pdf":
            process_pdf(input_path, output_path, waifu2x_path, tmp_dir, waifu2x_args, dpi=args.dpi)
        elif kind == "image":
            passthrough_image(input_path, output_path, waifu2x_path, waifu2x_args)
        else:
            parser.error("Unsupported input type. Use image, directory, PDF, EPUB, or MOBI.")
    finally:
        if not args.tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            debug(f"Cleaned up temporary directory {tmp_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
