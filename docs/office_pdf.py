"""PDF export for Windows, shared by build_report.py and build_deck.py.

macOS drives Word and PowerPoint through osascript (see each build script). On
Windows the same applications are driven through COM (pywin32), and LibreOffice
is the fallback. Returns None, after saying why, when neither is available, so
the caller can still keep the .docx or .pptx it just built.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# COM constants: Word wdFormatPDF, PowerPoint ppSaveAsPDF
WORD_PDF = 17
POWERPOINT_PDF = 32


def _office_com(path: Path, pdf: Path) -> bool:
    """Export through Word or PowerPoint; False if Office or pywin32 is missing."""
    try:
        import win32com.client  # pywin32, imported here so other platforms never need it

        if path.suffix.lower() == ".docx":
            app = win32com.client.Dispatch("Word.Application")
            app.DisplayAlerts = 0
            doc = app.Documents.Open(str(path), ReadOnly=True)
            try:
                doc.SaveAs2(str(pdf), FileFormat=WORD_PDF)
            finally:
                doc.Close(False)
                app.Quit()
        else:
            app = win32com.client.Dispatch("PowerPoint.Application")
            pres = app.Presentations.Open(str(path), ReadOnly=True, WithWindow=False)
            try:
                pres.SaveAs(str(pdf), POWERPOINT_PDF)
            finally:
                pres.Close()
                app.Quit()
    except Exception as exc:  # no pywin32, Office not installed, or COM failure
        print(f"  Office COM export unavailable ({type(exc).__name__}: {exc})")
        return False
    return pdf.exists()


def _soffice(path: Path, pdf: Path) -> bool:
    exe = shutil.which("soffice") or shutil.which("soffice.exe")
    if not exe:
        return False
    subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(pdf.parent), str(path)],
                   check=True, capture_output=True)
    return pdf.exists()


def export_pdf_windows(path: Path) -> Path | None:
    path = path.resolve()
    pdf = path.with_suffix(".pdf")
    if _office_com(path, pdf) or _soffice(path, pdf):
        return pdf
    print(f"  skipping PDF for {path.name}: needs Microsoft Office with pywin32 "
          "(pip install pywin32) or LibreOffice (soffice) on PATH")
    return None
