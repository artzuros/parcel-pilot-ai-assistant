import pathlib, shutil, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'data' / 'source'
OUT = ROOT / 'data' / 'extracted_text'

PDFS = [
    '01_Support_Policy_v3_CURRENT.pdf',
    '05_Northstar_Logistics_Enterprise_Agreement.pdf',
    '02_Support_Policy_v2_DEPRECATED.pdf',
    '06_LumenWorks_Service_Agreement.pdf',
    '03_Cancellation_and_Service_Credit_SOP_v4.pdf',
    '04_Product_Operations_Guide_and_Known_Issues.pdf'
]
def extract_pdftotext(pdf: pathlib.Path) -> str:
    r = subprocess.run(
        ['pdftotext', '-layout', str(pdf), '-'],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout

def extract_pypdf(pdf: pathlib.Path) -> str:
    "No poppler fallback"
    from pypdf import Pdfreader
    reader = Pdfreader(str(pdf))
    return "".join((page.extract_text() or "") for page in reader.pages)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    has_poppler = shutil.which("pdftotext") is not None
    
    for name in PDFS:
        pdf = SRC / name
        if not pdf.exists():
            print(f"Missing : {pdf}")
            continue
        text = extract_pdftotext(pdf) if has_poppler else extract_pypdf(pdf)
        out = OUT / (name.replace(".pdf", ".txt"))
        out.write_text(text, encoding="utf-8")
        print(f"{name}: {len(text)} chars IN {out.name}")

if __name__ == "__main__": main()