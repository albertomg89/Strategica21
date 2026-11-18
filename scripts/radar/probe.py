"""Radar della domanda - fase 1: sonda delle fonti (ISTAT SDMX, Eurostat).
Scopo: scoprire dataflow, dimensioni, copertura territoriale e ultimo periodo.
Non modifica la pagina. Scrive il report in data/radar/probe.json e nei log."""
import json, re, sys, time, datetime, os
os.makedirs("data/radar", exist_ok=True)
import requests

ISTAT = "https://esploradati.istat.it/SDMXWS/rest"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
S = requests.Session()
S.headers["User-Agent"] = "strategica21-radar/0.1 (+https://strategica21.com)"
report = {"run_at": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z", "istat": {}, "eurostat": {}}

def get(url, accept=None, params=None, timeout=90):
    h = {"Accept": accept} if accept else {}
    try:
        r = S.get(url, headers=h, params=params, timeout=timeout)
        return r
    except Exception as e:
        print("ERR", url, e)
        return None

# ---------- ISTAT: scoperta dei dataflow sui prezzi al consumo ----------
print("== ISTAT: elenco dataflow")
r = get(f"{ISTAT}/dataflow/IT1", accept="application/xml")
report["istat"]["dataflow_status"] = getattr(r, "status_code", None)
flows = []
if r is not None and r.ok:
    txt = r.text
    print("dataflow bytes:", len(txt))
    for m in re.finditer(r'<(?:\w+:)?Dataflow\b([^>]*)>(.*?)</(?:\w+:)?Dataflow>', txt, re.S):
        attrs, body = m.group(1), m.group(2)
        fid = re.search(r'\bid="([^"]+)"', attrs)
        ver = re.search(r'\bversion="([^"]+)"', attrs)
        name = re.search(r'<(?:\w+:)?Name xml:lang="it">([^<]+)</', body) or re.search(r'<(?:\w+:)?Name[^>]*>([^<]+)</', body)
        flows.append({"id": fid and fid.group(1), "version": ver and ver.group(1), "name": name and name.group(1)})
    print("dataflow totali:", len(flows))
    if not flows:
        i = txt.find("NIC1B2025"); print("contesto NIC1B2025:", txt[max(0,i-300):i+500] if i>=0 else "assente"); print("inizio XML:", txt[:600])
    nic = [f for f in flows if f["id"] and ("NIC" in f["id"] or (f["name"] and re.search(r"prezzi al consumo|NIC", f["name"], re.I)))]
    report["istat"]["nic_flows"] = nic
    for f in nic:
        print(" NIC>", f)
else:
    print("ISTAT dataflow KO", getattr(r, "status_code", None), (r.text[:300] if r is not None else ""))

# ---------- ISTAT: dati di un dataflow NIC ----------
def istat_sample(fid, ver):
    time.sleep(15)  # limite ISTAT ~5 richieste/minuto
    url = f"{ISTAT}/data/IT1,{fid},{ver}/all"
    r = get(url, accept="application/vnd.sdmx.data+csv;version=1.0.0", params={"startPeriod": "2025-01"}, timeout=180)
    if r is None or not r.ok:
        print("  dati KO", fid, getattr(r, "status_code", None), (r.text[:200] if r is not None else ""))
        return {"status": getattr(r, "status_code", None)}
    lines = r.text.splitlines()
    head = lines[0].split(",") if lines else []
    print(f"  {fid}: {len(lines)-1} righe; colonne={head}")
    out = {"status": 200, "rows": len(lines) - 1, "columns": head}
    try:
        import csv, io
        rows = list(csv.DictReader(io.StringIO(r.text)))
        keycols = [c for c in head if c in ("REF_AREA", "TIME_PERIOD", "DATA_TYPE", "ECOICOP_2", "MEASURE", "COICOP", "ECOICOP")]
        for c in keycols:
            vals = sorted({x[c] for x in rows})
            out[c] = vals if len(vals) <= 60 else {"n": len(vals), "first": vals[:8], "last": vals[-8:]}
        open(f"data/radar/sample_{fid}.csv", "w").write("\n".join(lines[:2000]))
    except Exception as e:
        out["parse_error"] = str(e)
    return out

report["istat"]["samples"] = {}
for f in (report["istat"].get("nic_flows") or [])[:6]:
    print("== ISTAT dati:", f["id"], f["version"])
    report["istat"]["samples"][f["id"]] = istat_sample(f["id"], f["version"])

# ---------- Eurostat ----------
def eurostat(code, **params):
    p = {"format": "JSON", "lang": "en"}; p.update(params)
    r = get(f"{EUROSTAT}/{code}", params=p, timeout=120)
    res = {"status": getattr(r, "status_code", None)}
    if r is not None and r.ok:
        j = r.json()
        dims = j.get("id", [])
        res["dims"] = {d: j["size"][i] for i, d in enumerate(dims)}
        tdim = j.get("dimension", {}).get("time", {}).get("category", {}).get("index", {})
        res["periodi"] = sorted(tdim)[-3:] if tdim else None
        res["updated"] = j.get("updated")
    else:
        res["body"] = (r.text[:200] if r is not None else "")
    print("Eurostat", code, res)
    return res

report["eurostat"]["prc_hicp_manr"] = eurostat("prc_hicp_manr", coicop="CP00", sinceTimePeriod="2026-06")
report["eurostat"]["sts_trtu_m"] = eurostat("sts_trtu_m", sinceTimePeriod="2026-06", s_adj="SCA", unit="I21", nace_r2="G47")
report["eurostat"]["ei_bsco_m"] = eurostat("ei_bsco_m", sinceTimePeriod="2026-06", indic="BS-CSMCI", s_adj="SA", unit="BAL")
report["eurostat"]["prc_hicp_manr_IT"] = eurostat("prc_hicp_manr", geo="IT", coicop="CP00")
for code in ("prc_hicp_minr","prc_hicp_cmon","prc_hicp_ctrb","tour_occ_nim"):
    report["eurostat"][code] = eurostat(code, geo="IT", sinceTimePeriod="2026-06")
report["eurostat"]["une_rt_m"] = eurostat("une_rt_m", sinceTimePeriod="2026-06", s_adj="SA", age="TOTAL", sex="T", unit="PC_ACT")
report["eurostat"]["lfst_r_lfu3rt"] = eurostat("lfst_r_lfu3rt", sinceTimePeriod="2025-Q1", sex="T", age="Y15-74")

json.dump(report, open("data/radar/probe.json", "w"), ensure_ascii=False, indent=1)
print("report scritto")
