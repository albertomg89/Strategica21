"""Radar della domanda - costruzione dei dati per la mappa dei prezzi per regione.
Fonte: ISTAT, indici dei prezzi al consumo NIC (ECOICOP v2), dataflow 'tutte le basi'.
Uscite: data/radar/regioni.json (serie per regione e divisione di spesa) e data/radar/regioni.geojson."""
import csv, datetime, io, json, os, re, sys, time
import requests

OUT = "data/radar"
os.makedirs(OUT, exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = "strategica21-radar/0.2 (+https://strategica21.com)"
URL = "https://esploradati.istat.it/SDMXWS/rest/data/IT1,167_745_DF_DCSP_NIC1B2025_6,1.0/all"

DIVISIONI = {
    "00": "Indice generale",
    "01": "Alimentari e bevande analcoliche",
    "02": "Bevande alcoliche, tabacco e narcotici",
    "03": "Abbigliamento e calzature",
    "04": "Abitazione, acqua, energia e combustibili",
    "05": "Mobili e servizi per la casa",
    "06": "Salute",
    "07": "Trasporti",
    "08": "Informazione e comunicazione",
    "09": "Ricreazione, sport e cultura",
    "10": "Istruzione",
    "11": "Ristorazione e alloggio",
    "12": "Assicurazioni e servizi finanziari",
    "13": "Cura della persona e beni vari",
}
# Regioni (NUTS2) + Italia. Bolzano e Trento sono distinte nei dati ISTAT; nella mappa usiamo il Trentino-Alto Adige (ITDA).
REGIONI = {
    "ITC1": "Piemonte", "ITC2": "Valle d'Aosta", "ITC3": "Liguria", "ITC4": "Lombardia",
    "ITDA": "Trentino-Alto Adige", "ITD3": "Veneto", "ITD4": "Friuli-Venezia Giulia", "ITD5": "Emilia-Romagna",
    "ITE1": "Toscana", "ITE2": "Umbria", "ITE3": "Marche", "ITE4": "Lazio",
    "ITF1": "Abruzzo", "ITF2": "Molise", "ITF3": "Campania", "ITF4": "Puglia", "ITF5": "Basilicata", "ITF6": "Calabria",
    "ITG1": "Sicilia", "ITG2": "Sardegna",
}
AREE = dict(REGIONI, IT="Italia")

# ---- 1. dati ISTAT ----
r = None
for attempt in range(3):
    time.sleep(15)
    try:
        r = S.get(URL, headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"},
                  params={"startPeriod": "2025-01"}, timeout=500)
        if r.ok: break
        print("tentativo", attempt + 1, r.status_code, r.text[:200])
    except Exception as e:
        print("tentativo", attempt + 1, "errore", e)
if r is None or not r.ok:
    sys.exit("ISTAT non raggiungibile: dati non aggiornati")

series = {}   # (area, cat, measure) -> {period: value}
for x in csv.DictReader(io.StringIO(r.text)):
    a, c, m = x["REF_AREA"], x["ECOICOP_2"], x["MEASURE"]
    if a not in AREE or c not in DIVISIONI or m not in ("4", "6", "7"): continue
    if x["OBS_VALUE"] in ("", None): continue
    # base 2015 (DATA_TYPE 39) fino al 2025, base 2025 (85) dal 2026: le variazioni % sono già calcolate da ISTAT
    dt, p = x["DATA_TYPE"], x["TIME_PERIOD"]
    if (dt == "39" and p <= "2025-12") or (dt == "85" and p >= "2026-01"):
        series.setdefault((a, c, m), {})[p] = float(x["OBS_VALUE"])

periods = sorted({p for s in series.values() for p in s})
last = max(p for (a, c, m), s in series.items() if (a, c, m) == ("IT", "00", "7") for p in s)
months = [p for p in periods if p <= last]
print("periodo:", months[0], "->", last, "| serie:", len(series))

def arr(a, c, m):
    s = series.get((a, c, m), {})
    return [s.get(p) for p in months]

data = {}
missing = []
for a in AREE:
    data[a] = {}
    for c in DIVISIONI:
        yoy, mom, idx = arr(a, c, "7"), arr(a, c, "6"), arr(a, c, "4")
        if yoy[-1] is None: missing.append((a, c))
        data[a][c] = {"yoy": yoy, "mom": mom, "idx": idx[-1]}
print("serie ultime mancanti:", len(missing), missing[:20])

out = {
    "ultimo_periodo": last, "mesi": months,
    "fonte": "ISTAT, indici dei prezzi al consumo per l'intera collettività (NIC), ECOICOP v2",
    "divisioni": DIVISIONI, "aree": AREE, "dati": data,
}
json.dump(out, open(f"{OUT}/regioni.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("regioni.json", os.path.getsize(f"{OUT}/regioni.json"), "byte")
for c in ("00", "01", "04", "07"):
    print("IT", c, DIVISIONI[c], "yoy ultimi", data["IT"][c]["yoy"][-3:], "mom", data["IT"][c]["mom"][-1])
yy = sorted((data[a]["00"]["yoy"][-1], AREE[a]) for a in REGIONI if data[a]["00"]["yoy"][-1] is not None)
print("indice generale yoy per regione:", yy)

# ---- 2. geometria delle regioni (semplificata) ----
try:
    if os.path.exists(f"{OUT}/regioni.geojson") and not os.environ.get("FORCE_GEO"):
        raise StopIteration
    from shapely.geometry import shape, mapping
    g = S.get("https://raw.githubusercontent.com/openpolis/geojson-italy/master/geojson/limits_IT_regions.geojson", timeout=120)
    g.raise_for_status()
    gj = g.json()
    def norm(n): return re.sub(r"[^a-z]", "", n.lower().split("/")[0].replace("è", "e").replace("'", ""))
    by_name = {norm(v): k for k, v in REGIONI.items()}
    by_name[norm("Valle d Aosta")] = "ITC2"; by_name[norm("Trentino-Alto Adige")] = "ITDA"
    feats = []
    for f in gj["features"]:
        nm = f["properties"].get("reg_name", "")
        code = by_name.get(norm(nm))
        if not code:
            print("regione non mappata:", nm); continue
        geom = shape(f["geometry"]).simplify(0.01, preserve_topology=True)
        m = mapping(geom)
        def rnd(c): return [rnd(i) for i in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 3), round(c[1], 3)]
        feats.append({"type": "Feature", "properties": {"code": code, "name": REGIONI[code]},
                      "geometry": {"type": m["type"], "coordinates": rnd(m["coordinates"])}})
    print("regioni in geojson:", len(feats), "di", len(REGIONI))
    json.dump({"type": "FeatureCollection", "features": feats}, open(f"{OUT}/regioni.geojson", "w"), separators=(",", ":"))
    print("regioni.geojson", os.path.getsize(f"{OUT}/regioni.geojson"), "byte")
except StopIteration:
    print("geometrie già presenti: salto")
except Exception as e:
    print("GEOMETRIA KO:", repr(e))
