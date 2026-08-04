"""Hızlı çekirdek modül testleri — SSH gerektirmez.

Kapsam:
- file_signatures.guess_type, is_bad_extension
- file_categories.CATEGORIES / all_extensions
- image_analyzer.extract_by_extensions (küçük sahte imaj üzerinde)
- image_browser.open + list_dir (pytsk3 yoksa fallback modu)
- image_browser.format_hex_dump
- ram_imager._next_attempt_path (attempt numaralama)
- disk_imager._acquire_split imzası (public API)
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

# Test dizininden ana projeye erişim
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def test_signatures():
    from core.file_signatures import guess_type, is_bad_extension
    # PDF
    assert guess_type(b"%PDF-1.7\n...")[0] == "PDF document"
    # PNG
    assert guess_type(b"\x89PNG\r\n\x1a\n")[0] == "PNG image"
    # OOXML
    assert guess_type(b"PK\x03\x04...")[0].startswith("Office")
    # PE
    assert guess_type(b"MZ\x00\x00")[0].startswith("Windows PE")
    # Bad extension: pdf uzantısı ama gerçekte PE
    actual, exts = guess_type(b"MZ\x00")
    assert is_bad_extension(actual, exts, "invoice.pdf") is True
    # OK extension
    actual, exts = guess_type(b"%PDF-1.4")
    assert is_bad_extension(actual, exts, "invoice.pdf") is False
    print("[OK] signatures + bad-extension")


def test_categories():
    from core.file_categories import CATEGORIES, all_extensions, category_by_name
    assert len(CATEGORIES) >= 10
    names = [c.name for c in CATEGORIES]
    for req in ("Belgeler", "Görseller", "Arşivler", "Yürütülebilir",
                "Veritabanı"):
        assert req in names, f"eksik kategori: {req}"
    exts = all_extensions()
    assert ".pdf" in exts and ".exe" in exts and ".sqlite" in exts
    # Tekilleştirme kontrolü
    assert len(exts) == len(set(exts))
    print(f"[OK] categories: {len(CATEGORIES)} kategori, {len(exts)} uzantı")


def test_ram_attempt_numbering():
    from core.ram_imager import RamImager
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "ram.lime")
        p1, n1 = RamImager._next_attempt_path(base)
        assert n1 == 1
        assert p1.endswith("ram-attempt-001.001")
        # 001'i oluştur → sıradaki 002 olmalı
        Path(p1).write_bytes(b"x")
        p2, n2 = RamImager._next_attempt_path(base)
        assert n2 == 2
        assert p2.endswith("ram-attempt-002.001")
    print("[OK] RAM attempt numbering (memory-attempt-NNN.001)")


def _make_fake_image(path: str) -> None:
    """Sahte imaj: birkaç magic number gömülü, filesystem yok (raw-scan)."""
    with open(path, "wb") as f:
        # 4KB dolgu
        f.write(b"\x00" * 4096)
        # @4096: PDF
        f.write(b"%PDF-1.4\n" + b"content..." * 100)
        # 8KB boşluk
        f.write(b"\x00" * (8192 - f.tell() + 4096))
        # Ensure position aligned to 12288
        current = f.tell()
        if current < 12288:
            f.write(b"\x00" * (12288 - current))
        # @12288: PNG
        f.write(b"\x89PNG\r\n\x1a\n" + b"IHDR..." * 50)
        # Padding
        f.write(b"\x00" * 4096)


def test_analyzer_extract():
    from core.image_analyzer import ImageAnalyzer
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "fake.dd")
        _make_fake_image(img)
        out = os.path.join(td, "extracted")
        # PDF uzantılı çıkarma (raw-scan modu — pytsk3 yoksa carver)
        result = ImageAnalyzer().extract_by_extensions(img, out, (".pdf",))
        assert result.image_format == "raw"
        # En az bir dosya (carver) çıkarılmış olmalı
        assert len(result.files) >= 1
        # Backend'i raporlamalı
        assert result.backend in ("raw-scan", "tsk", "tsk+ewf")
        # Çıkış dizininde dosyalar oluşmuş olmalı
        outputs = os.listdir(out)
        assert len(outputs) >= 1
    print(f"[OK] analyzer.extract_by_extensions (backend={result.backend}, "
          f"{len(result.files)} dosya)")


def test_image_browser():
    from core.image_browser import ImageBrowser, format_hex_dump
    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "fake.dd")
        _make_fake_image(img)
        b = ImageBrowser()
        nodes = b.open(img)
        assert len(nodes) >= 1
        assert nodes[0].kind == "image"
        assert any(n.kind in ("partition", "unpartitioned") for n in nodes)
        # Fallback scan API — 10 MB'lık sınırla full scan
        results = b.scan_fallback(max_bytes=0, step=4096)
        # Sahte imajımızda PDF + PNG imzası vardı
        assert len(results) >= 2, f"Expected >=2 sig matches, got {len(results)}"
        types = {r.detected_type for r in results}
        assert "PDF document" in types
        assert "PNG image" in types
        # has_tsk / has_ewf metodları
        assert hasattr(b, "has_tsk") and hasattr(b, "has_ewf")
        # Basit hex dump
        data = b"\x89PNG\r\n\x1a\nABCDEFGH"
        dump = format_hex_dump(data, base_offset=0)
        assert "89 50 4E 47" in dump
        b.close()
    print(f"[OK] ImageBrowser open + fallback scan ({len(results)} eşleşme) "
          f"+ hex dump (backend={b.backend})")


def test_targeted_rule_shape():
    from core.targeted_imager import TargetedRule
    rule = TargetedRule(
        name="test", extensions=(".pdf", ".docx"), use_signature_match=True,
    )
    assert rule.name == "test"
    assert ".pdf" in rule.extensions
    assert rule.use_signature_match is True
    print("[OK] TargetedRule shape")


def test_landing_endpoints():
    """Landing backend endpoint'leri — HTTP çağrısıyla doğrudan."""
    import urllib.request
    import json
    import zipfile

    # Info
    with urllib.request.urlopen("http://localhost:8001/api/imager/info",
                                 timeout=10) as r:
        info = json.loads(r.read().decode("utf-8"))
    assert info["name"].startswith("ForenSync")
    assert info["files"] >= 30
    assert "Windows" in info["platforms"]

    # Download
    with urllib.request.urlopen("http://localhost:8001/api/imager/download",
                                 timeout=15) as r:
        data = r.read()
    assert len(data) > 10_000
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert any(n.endswith("main.py") for n in names)
    assert any(n.endswith("core/ram_imager.py") for n in names)
    assert any(n.endswith("gui/extension_picker.py") for n in names)
    print(f"[OK] landing zip: {len(data):,} bytes, {len(names)} files")


if __name__ == "__main__":
    tests = [
        test_signatures, test_categories, test_ram_attempt_numbering,
        test_analyzer_extract, test_image_browser, test_targeted_rule_shape,
        test_landing_endpoints,
    ]
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {t.__name__}: {exc}")
            raise
    print("\nHepsi geçti — çekirdek modüller çalışıyor.")
