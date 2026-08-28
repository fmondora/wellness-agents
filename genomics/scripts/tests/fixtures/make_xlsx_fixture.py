"""Genera sample.xlsx (fixture sintetica). Eseguire una volta: richiede openpyxl."""
from pathlib import Path
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.append(["Report genotipi — FIXTURE SINTETICA"])
ws.append([])
ws.append(["rsid", "chromosome", "position", "genotype"])
for row in [("rs1000001", "1", 1000, "AA"), ("rs1000002", "1", 2000, "AG"),
            ("rs1000009", "3", 9000, "--")]:
    ws.append(row)
wb.save(Path(__file__).parent / "sample.xlsx")
print("scritto sample.xlsx")
