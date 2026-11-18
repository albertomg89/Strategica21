"""Radar - decodifica dei codici ISTAT (DATA_TYPE, MEASURE, categorie, territori) dal dataflow 'tutte le basi'."""
import csv, io, json, os, time
import requests
os.makedirs("data/radar", exist_ok=True)
URL = "https://esploradati.istat.it/SDMXWS/rest/data/IT1,167_745_DF_DCSP_NIC1B2025_6,1.0/all"
S = requests.Session(); S.headers["User-Agent"] = "strategica21-radar/0.1"
for acc in ("application/vnd.sdmx.data+csv;version=1.0.0;labels=both", "application/vnd.sdmx.data+csv;version=1.0.0"):
    time.sleep(15)
    r = S.get(URL, headers={"Accept": acc}, params={"startPeriod": "2025-01"}, timeout=400)
    print("accept", acc, "->", r.status_code, len(r.text))
    if r.ok: break
rows = list(csv.DictReader(io.StringIO(r.text)))
print("COLS", list(rows[0].keys()))
for c in ("FREQ", "DATA_TYPE", "MEASURE", "UNIT_MEAS", "UNIT_MULT", "BASE_PER", "OBS_STATUS"):
    print("VALS", c, sorted({x.get(c, "") for x in rows})[:20])
def show(area, cat_sub, n=14):
    sel = [x for x in rows if x["REF_AREA"].split(":")[0].strip() == area and cat_sub in x["ECOICOP_2"]]
    ks = sorted({(x["DATA_TYPE"], x["MEASURE"], x["ECOICOP_2"]) for x in sel})[:6]
    for k in ks:
        ser = sorted((x["TIME_PERIOD"], x["OBS_VALUE"]) for x in sel if (x["DATA_TYPE"], x["MEASURE"], x["ECOICOP_2"]) == k)
        print("SERIE", area, k, ser[:3], "...", ser[-3:], "n=", len(ser))
show("IT", "")
show("ITC4", "")
areas = sorted({x["REF_AREA"] for x in rows})
print("AREAS", len(areas), areas[:200])
cats = sorted({x["ECOICOP_2"] for x in rows})
print("CATS", len(cats), cats[:80])
json.dump({"areas": areas, "cats": cats}, open("data/radar/labels.json", "w"), ensure_ascii=False)
