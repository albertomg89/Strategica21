"""Radar Europa: dati Eurostat per Paese (prezzi per divisione, vendite al dettaglio, fiducia consumatori)
e geometrie dei Paesi. Pensato per girare su GitHub Actions (la rete è aperta lì)."""
import json, os, sys, time, itertools
import requests

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
OUT = "data/radar"
os.makedirs(OUT, exist_ok=True)

PAESI = {  # codice Eurostat -> (nome, ISO2)
    "AT": ("Austria", "AT"), "BE": ("Belgio", "BE"), "BG": ("Bulgaria", "BG"), "HR": ("Croazia", "HR"),
    "CY": ("Cipro", "CY"), "CZ": ("Cechia", "CZ"), "DK": ("Danimarca", "DK"), "EE": ("Estonia", "EE"),
    "FI": ("Finlandia", "FI"), "FR": ("Francia", "FR"), "DE": ("Germania", "DE"), "EL": ("Grecia", "GR"),
    "HU": ("Ungheria", "HU"), "IE": ("Irlanda", "IE"), "IT": ("Italia", "IT"), "LV": ("Lettonia", "LV"),
    "LT": ("Lituania", "LT"), "LU": ("Lussemburgo", "LU"), "MT": ("Malta", "MT"), "NL": ("Paesi Bassi", "NL"),
    "PL": ("Polonia", "PL"), "PT": ("Portogallo", "PT"), "RO": ("Romania", "RO"), "SK": ("Slovacchia", "SK"),
    "SI": ("Slovenia", "SI"), "ES": ("Spagna", "ES"), "SE": ("Svezia", "SE"),
    "NO": ("Norvegia", "NO"), "CH": ("Svizzera", "CH"), "IS": ("Islanda", "IS"),
}
AGGR = {"EU27_2020": "UE27", "EA20": "Area euro"}
GEO = list(PAESI) + ["EU27_2020", "EA20"]

DIVISIONI = {"00": "Indice generale", "01": "Alimentari e bevande analcoliche", "02": "Bevande alcoliche, tabacco e narcotici",
             "03": "Abbigliamento e calzature", "04": "Abitazione, acqua, energia e combustibili", "05": "Mobili e servizi per la casa",
             "06": "Salute", "07": "Trasporti", "08": "Informazione e comunicazione", "09": "Ricreazione, sport e cultura",
             "10": "Istruzione", "11": "Ristorazione e alloggio", "12": "Assicurazioni e servizi finanziari", "13": "Cura della persona e beni vari"}

report = {}


def get(dataset, params, retries=4):
    q = [("format", "JSON"), ("lang", "EN")] + params
    url = BASE + dataset
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=q, timeout=120, headers={"Accept": "application/json"})
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                return r.json()
            last = f"HTTP {r.status_code} {r.headers.get('content-type')} {r.text[:200]!r}"
        except Exception as e:
            last = repr(e)
        time.sleep(8 * (i + 1))
    report[dataset] = {"errore": last}
    print("ERRORE", dataset, last)
    return None


def parse(js):
    """JSON-stat -> (dims: {id: [codes in order]}, values: dict{tuple(codes): float})"""
    ids = js["id"]; size = js["size"]
    cats = {}
    for d in ids:
        idx = js["dimension"][d]["category"]["index"]
        if isinstance(idx, list):
            idx = {c: i for i, c in enumerate(idx)}
        cats[d] = [c for c, _ in sorted(idx.items(), key=lambda x: x[1])]
    vals = js.get("value", {})
    if isinstance(vals, list):
        vals = {i: v for i, v in enumerate(vals) if v is not None}
    strides = []
    s = 1
    for n in reversed(size):
        strides.append(s); s *= n
    strides = list(reversed(strides))
    out = {}
    for k, v in vals.items():
        k = int(k)
        key = []
        for d, st, n in zip(ids, strides, size):
            key.append(cats[d][(k // st) % n])
        out[tuple(key)] = v
    return ids, cats, out


def month_range(a, b):
    y, m = map(int, a.split("-")); y2, m2 = map(int, b.split("-"))
    res = []
    while (y, m) <= (y2, m2):
        res.append(f"{y}-{m:02d}"); m += 1
        if m > 12: y += 1; m = 1
    return res


series = {"prezzi": {}, "vendite": {}, "fiducia": {}}
all_months = set()

# ---- 1. Prezzi: HICP tasso annuo per divisione COICOP 2018 ----
js = get("prc_hicp_minr", [("freq", "M"), ("unit", "RCH_A"), ("sinceTimePeriod", "2025-01")] + [("geo", g) for g in GEO])
if js:
    ids, cats, vals = parse(js)
    report["prc_hicp_minr"] = {"dim": ids, "coicop18": cats.get("coicop18", [])[:40], "updated": js.get("updated")}
    ci = ids.index("coicop18"); gi = ids.index("geo"); ti = ids.index("time")
    for key, v in vals.items():
        c = key[ci]
        div = "00" if c in ("TOTAL", "CP00") else (c[2:] if c.startswith("CP") and len(c) == 4 and c[2:].isdigit() else None)
        if div not in DIVISIONI:
            continue
        series["prezzi"].setdefault(div, {}).setdefault(key[gi], {})[key[ti]] = v
        all_months.add(key[ti])

# ---- 2. Vendite al dettaglio (volume, destagionalizzato) ----
js = get("sts_trtu_m", [("freq", "M"), ("indic_bt", "VOL_SLS"), ("nace_r2", "G47"), ("s_adj", "SCA"), ("sinceTimePeriod", "2024-01")] + [("geo", g) for g in GEO])
if js:
    ids, cats, vals = parse(js)
    report["sts_trtu_m"] = {"dim": ids, "unit": cats.get("unit"), "updated": js.get("updated")}
    ui = ids.index("unit") if "unit" in ids else None
    units = cats.get("unit", [])
    unit = "I21" if "I21" in units else (units[0] if units else None)
    gi = ids.index("geo"); ti = ids.index("time")
    for key, v in vals.items():
        if ui is not None and key[ui] != unit:
            continue
        series["vendite"].setdefault(key[gi], {})[key[ti]] = v

# ---- 3. Fiducia dei consumatori (saldo) ----
js = get("ei_bsco_m", [("freq", "M"), ("indic", "BS-CSMCI"), ("s_adj", "SA"), ("unit", "BAL"), ("sinceTimePeriod", "2025-01")] + [("geo", g) for g in GEO])
if js:
    ids, cats, vals = parse(js)
    report["ei_bsco_m"] = {"dim": ids, "updated": js.get("updated")}
    gi = ids.index("geo"); ti = ids.index("time")
    for key, v in vals.items():
        series["fiducia"].setdefault(key[gi], {})[key[ti]] = v
        all_months.add(key[ti])

if not all_months:
    print("Nessun dato: esco"); json.dump(report, open(f"{OUT}/europa_report.json", "w"), indent=1); sys.exit(1)

mesi = month_range("2025-01", max(all_months))
ultimo_prezzi = max((m for d in series["prezzi"].values() for g in d.values() for m in g), default=None)


def arr(d):
    return [d.get(m) for m in mesi]


def yoy(d):
    out = []
    for m in mesi:
        y, mm = m.split("-"); p = f"{int(y)-1}-{mm}"
        a, b = d.get(m), d.get(p)
        out.append(round((a / b - 1) * 100, 2) if a is not None and b else None)
    return out


nomi = {g: PAESI[g][0] for g in PAESI}
nomi.update(AGGR)
res = {
    "aggiornato": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "fonte": "Eurostat (prc_hicp_minr, sts_trtu_m, ei_bsco_m)",
    "mesi": mesi,
    "paesi": nomi,
    "iso2": {g: PAESI[g][1] for g in PAESI},
    "divisioni": DIVISIONI,
    "prezzi": {div: {g: arr(d) for g, d in geos.items()} for div, geos in series["prezzi"].items()},
    "vendite": {g: {"yoy": yoy(d), "idx": arr(d)} for g, d in series["vendite"].items()},
    "fiducia": {g: arr(d) for g, d in series["fiducia"].items()},
}
json.dump(res, open(f"{OUT}/europa.json", "w"), separators=(",", ":"), ensure_ascii=False)
print("europa.json", os.path.getsize(f"{OUT}/europa.json"), "bytes; mesi", mesi[0], mesi[-1],
      "| prezzi div", len(res["prezzi"]), "| vendite paesi", len(res["vendite"]), "| fiducia paesi", len(res["fiducia"]))
if ultimo_prezzi:
    tot = res["prezzi"].get("00", {})
    i = mesi.index(ultimo_prezzi)
    print("ultimo prezzi", ultimo_prezzi, {g: tot[g][i] for g in ("IT", "DE", "FR", "ES", "EU27_2020") if g in tot})

# ---- 4. Geometrie dei Paesi (Natural Earth 50m, ritagliate sull'Europa) ----
try:
    from shapely.geometry import shape, box, mapping
    URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
    gj = requests.get(URL, timeout=180).json()
    clip = box(-25, 34, 45, 72)
    iso2eu = {v[1]: k for k, v in PAESI.items()}
    feats = []
    for f in gj["features"]:
        p = f["properties"]
        iso = p.get("ISO_A2_EH") or p.get("ISO_A2")
        if iso in ("-99", None) or iso not in iso2eu:
            iso = {"FRA": "FR", "NOR": "NO"}.get(p.get("ADM0_A3"), iso)
        if iso not in iso2eu:
            continue
        g = shape(f["geometry"]).intersection(clip).simplify(0.03)
        if g.is_empty:
            continue
        # arrotonda le coordinate
        def rnd(o):
            return [rnd(x) for x in o] if isinstance(o, (list, tuple)) and o and isinstance(o[0], (list, tuple)) else [round(c, 2) for c in o]
        m = mapping(g)
        feats.append({"type": "Feature", "properties": {"code": iso2eu[iso], "name": PAESI[iso2eu[iso]][0]},
                      "geometry": {"type": m["type"], "coordinates": rnd(m["coordinates"])}})
    json.dump({"type": "FeatureCollection", "features": feats}, open(f"{OUT}/europa.geojson", "w"), separators=(",", ":"))
    print("europa.geojson", os.path.getsize(f"{OUT}/europa.geojson"), "bytes;", len(feats), "paesi su", len(PAESI))
    report["geojson"] = {"paesi": len(feats), "mancanti": sorted(set(PAESI) - {x["properties"]["code"] for x in feats})}
except Exception as e:
    print("ERRORE geometrie", repr(e)); report["geojson"] = {"errore": repr(e)}

json.dump(report, open(f"{OUT}/europa_report.json", "w"), indent=1)
