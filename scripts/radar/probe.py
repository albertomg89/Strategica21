"""Radar della domanda - sonda delle fonti (ISTAT SDMX, Eurostat).
Scopo: verificare copertura territoriale, dettaglio per categoria e ultimo periodo.
Non modifica la pagina. Scrive il report in data/radar/probe.json e un riepilogo nei log."""
import csv, datetime, io, json, os, time
import requests

os.makedirs("data/radar", exist_ok=True)
ISTAT = "https://esploradati.istat.it/SDMXWS/rest"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
S = requests.Session()
S.headers["User-Agent"] = "strategica21-radar/0.1 (+https://strategica21.com)"
report = {"run_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "istat": {}, "eurostat": {}}


def get(url, accept=None, params=None, timeout=90):
    try:
        return S.get(url, headers={"Accept": accept} if accept else {}, params=params, timeout=timeout)
    except Exception as e:  # rete, timeout
        print("ERR", url, e)
        return None


# ---------- ISTAT: dataflow NIC base 2025 (ID trovati nella sonda precedente) ----------
FLOWS = {
    "167_745_DF_DCSP_NIC1B2025_2": "Tipologie di prodotto",
    "167_745_DF_DCSP_NIC1B2025_3": "Ecoicop 2 (3 cifre) - prov.",
    "167_745_DF_DCSP_NIC1B2025_6": "mensili - tutte le basi - Ecoicop 2",
}


def istat_sample(fid):
    url = f"{ISTAT}/data/IT1,{fid},1.0/all"
    r = None
    for attempt in range(3):
        time.sleep(15)  # limite ISTAT ~5 richieste/minuto
        r = get(url, accept="application/vnd.sdmx.data+csv;version=1.0.0",
                params={"startPeriod": "2025-01"}, timeout=300)
        if r is not None and r.ok:
            break
        print("  tentativo", attempt + 1, "fallito", getattr(r, "status_code", None))
    if r is None or not r.ok:
        return {"status": getattr(r, "status_code", None)}
    rows = list(csv.DictReader(io.StringIO(r.text)))
    out = {"status": 200, "rows": len(rows), "columns": list(rows[0].keys()) if rows else []}
    ref = {}
    for x in rows:
        ref.setdefault(x["REF_AREA"], set()).add(x["ECOICOP_2"])
    out["serie_per_territorio"] = {k: len(v) for k, v in sorted(ref.items())}
    out["ultimo_periodo"] = max(x["TIME_PERIOD"] for x in rows)
    out["primo_periodo"] = min(x["TIME_PERIOD"] for x in rows)
    out["data_types"] = sorted({x["DATA_TYPE"] for x in rows})
    out["measures"] = sorted({x["MEASURE"] for x in rows})
    out["categorie_esempio"] = sorted({x["ECOICOP_2"] for x in rows})[:40]
    out["n_categorie"] = len({x["ECOICOP_2"] for x in rows})
    with open(f"data/radar/sample_{fid}.csv", "w") as fh:
        fh.write("\n".join(r.text.splitlines()[:300]))
    return out


report["istat"]["samples"] = {}
for fid, nm in FLOWS.items():
    print("== ISTAT dati:", fid, nm)
    report["istat"]["samples"][fid] = istat_sample(fid)


# ---------- Eurostat ----------
def eurostat(code, **params):
    p = {"format": "JSON", "lang": "en"}
    p.update(params)
    r = get(f"{EUROSTAT}/{code}", params=p, timeout=120)
    res = {"status": getattr(r, "status_code", None)}
    if r is not None and r.ok:
        j = r.json()
        res["dims"] = {d: j["size"][i] for i, d in enumerate(j.get("id", []))}
        tdim = j.get("dimension", {}).get("time", {}).get("category", {}).get("index", {})
        res["periodi"] = sorted(tdim)[-3:] if tdim else None
        res["updated"] = j.get("updated")
    print("Eurostat", code, res)
    return res


report["eurostat"]["sts_trtu_m"] = eurostat("sts_trtu_m", sinceTimePeriod="2026-06", s_adj="SCA", unit="I21", nace_r2="G47")
report["eurostat"]["prc_hicp_minr"] = eurostat("prc_hicp_minr", geo="IT", sinceTimePeriod="2026-06")
report["eurostat"]["ei_bsco_m"] = eurostat("ei_bsco_m", sinceTimePeriod="2026-06", indic="BS-CSMCI", s_adj="SA", unit="BAL")
report["eurostat"]["tour_occ_nim"] = eurostat("tour_occ_nim", geo="IT", sinceTimePeriod="2026-06")

with open("data/radar/probe.json", "w") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1)

for fid, v in report["istat"]["samples"].items():
    print("SUMMARY", fid, "righe", v.get("rows"), "periodi", v.get("primo_periodo"), "->", v.get("ultimo_periodo"),
          "territori", len(v.get("serie_per_territorio", {})), "categorie", v.get("n_categorie"))
    print("SUMMARY  territori:", json.dumps(v.get("serie_per_territorio", {}), ensure_ascii=False)[:2500])
    print("SUMMARY  data_types:", v.get("data_types"), "measures:", v.get("measures"))
print("report scritto")
