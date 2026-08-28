import gzip, hashlib, sys, importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIXTURES = Path(__file__).parent / "fixtures"

# Import MINI before we start manipulating modules
_test_clinvar_path = Path(__file__).parent / "test_annotate_clinvar.py"
spec = importlib.util.spec_from_file_location("test_annotate_clinvar", _test_clinvar_path)
_test_clinvar_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_test_clinvar_mod)
MINI_DATA = _test_clinvar_mod.MINI


def _run_all(root, monkeypatch) -> str:
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WELLNESS_DATA", str(root))
    for m in list(sys.modules):
        if m.startswith("dna_"):
            del sys.modules[m]
    import dna_ingest, dna_annotate, dna_report
    vcf = root / "mini.vcf.gz"
    with gzip.open(vcf, "wt") as fh:
        fh.write(MINI_DATA)
    dna_ingest.ingest(FIXTURES / "sample_23andme.txt")
    dna_annotate.annotate_panels(FIXTURES / "panels")
    dna_annotate.annotate_clinvar(vcf_path=vcf)
    h = hashlib.sha256()
    for f in sorted((root / "data" / "dna" / "annotated").glob("*.jsonl")):
        h.update(f.read_bytes())
    h.update(dna_report.report_panels().read_bytes())
    h.update(dna_report.report_clinvar().read_bytes())
    return h.hexdigest()


def test_pipeline_deterministica(tmp_path, monkeypatch):
    a = _run_all(tmp_path / "a", monkeypatch)
    b = _run_all(tmp_path / "b", monkeypatch)
    assert a == b
