"""Genera sample.xlsx (fixture sintetica). Eseguire una volta: richiede openpyxl."""
from pathlib import Path
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.append(["Report genotipi — FIXTURE SINTETICA"])
ws.append([])
ws.append(["# rsid", "chromosome", "position", "genotype"])
for row in [("rs1000001", 1.0, 1000.0, "AA"), ("rs1000002", 1.0, 2000.0, "AG"),
            ("rs1000009", 3.0, 9000.0, "--")]:
    ws.append(row)
wb.save(Path(__file__).parent / "sample.xlsx")
print("scritto sample.xlsx")
