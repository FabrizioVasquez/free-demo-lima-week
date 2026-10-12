"""Búsqueda semántica + ponderación explicable.

1. Interpreta el prompt (días, horario, distrito, formato, objetivos).
2. Recupera fragmentos similares desde LanceDB (vectores locales) con prefiltros.
3. Puntúa cada evento en 5 criterios con pesos que se adaptan a lo que pediste.
4. Devuelve el rastro de razonamiento de cada decisión, incluidos los eventos descartados.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from .config import EVENTS_JSON
from .embed import embed
from .index import table

LIMA = timezone(timedelta(hours=-5))
FMT = "%Y-%m-%d %H:%M"
WEEK = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18"]
DAY_NAMES = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
DOW = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
NUM = {"un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8}

CITY_ALIASES = {
    "surco": "Santiago de Surco",
    "magdalena": "Magdalena del Mar",
    "arequipa": "José Luis Bustamante",
    "centro de lima": "Cercado de Lima",
    "cercado": "Cercado de Lima",
    "ves": "Villa EL Salvador",
    "villa el salvador": "Villa EL Salvador",
    "molina": "La Molina",
    "punta": "La Punta",
}

STOP = set(
    """quiero busco necesito tengo puedo prefiero estoy donde desde hasta para como pero porque cuando sobre entre
tambien algo mucho muchos poco todo todos esta este estos otro otros solo solamente vivo eventos evento gente cosas
cualquier cuenta semana momento mejor mejores ciclo años anos nivel tipo quien alguna algun tener hacer hace sido tiempo
dias lima distrito conocer ayuda quisiera gustaria interesa interesan nuevo nueva nuevos""".split()
)

GOALS = {
    "aprender": r"aprend|entender|formacion|capacit|estudi|curso|masterclass|conocimiento|dominar|profundiz",
    "networking": r"network|conocer gente|contactos|conectar|relacion|comunidad|socializ|mentor|referent",
    "empleo": r"practic|empleo|trabajo|contrat|reclut|chamba|oportunidad laboral|carrera|entrevista|cv\b",
    "inversion": r"invers|capital|fundrais|levant|\bvc\b|venture|financiamiento|\bseed\b|ronda",
    "construir": r"construir|construy|hackathon|proyecto|prototip|codear|programar|\bbuild|lanzar|mvp",
}
GOAL_LABEL = {
    "aprender": "Aprender",
    "networking": "Networking",
    "empleo": "Empleo / prácticas",
    "inversion": "Inversión",
    "construir": "Construir",
}
SIGNALS = {
    "aprender": [
        "workshop",
        "taller",
        "masterclass",
        "charla",
        "conferencia",
        "conf",
        "summit",
        "aprend",
        "hands-on",
        "curso",
        "conversatorio",
        "foro",
        "capacit",
        "keynote",
    ],
    "networking": [
        "networking",
        "mixer",
        "happy hour",
        "coctel",
        "cocktail",
        "after office",
        "meetup",
        "encuentro",
        "comunidad",
        "community",
        "speed dating",
        "founders",
        "brunch",
        "desayuno",
        "mentor",
    ],
    "empleo": ["talento", "contrata", "hiring", "empleo", "reclut", "practic", "carrera", "talent", "oportunidades", "empleabilidad"],
    "inversion": [
        "venture",
        "vc",
        "inversion",
        "inversionista",
        "fundraising",
        "capital",
        "fondo",
        "seed",
        "pitch",
        "demo day",
        "levantar",
        "ventures",
    ],
    "construir": [
        "hackathon",
        "hack",
        "construye",
        "construir",
        "build",
        "taller",
        "workshop",
        "prototipo",
        "mvp",
        "codigo",
        "code",
        "hands-on",
        "laptop",
    ],
}
OUTSIDE_LIMA = {"Trujillo", "Chiclayo", "José Luis Bustamante", "Huancayo"}  # otras regiones: requieren viaje
W_BASE = {"semantica": 45, "objetivo": 20, "disponibilidad": 15, "escala": 10, "logistica": 10}
CRIT_LABEL = {
    "semantica": "Afinidad semántica",
    "objetivo": "Calce con tu objetivo",
    "disponibilidad": "Disponibilidad",
    "escala": "Alcance de la comunidad",
    "logistica": "Logística",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def now_lima() -> str:
    return os.environ.get("BTW_NOW") or datetime.now(LIMA).strftime(FMT)


def load_events() -> dict[str, dict]:
    return {e["id"]: e for e in json.loads(EVENTS_JSON.read_text(encoding="utf-8"))}


def day_label(d: str) -> str:
    t = datetime.strptime(d, "%Y-%m-%d")
    return f"{DOW[t.weekday()]} {t.day}"


def _stem(w: str) -> str:
    return w[:5] if len(w) > 5 else w


# ---------------------------------------------------------------- interpretación
def parse_intent(prompt: str, cities: list[str], today: str) -> dict:
    p = norm(prompt)
    out = {"days": [], "time": None, "city": None, "mode": None, "mode_hard": False, "top_n": None, "goals": []}

    morning = re.search(r"(por|en|de|a) la manana|temprano|madrugad|desayun", p)
    q = p
    if morning:
        out["time"] = "mañana"
        q = re.sub(r"(por|en|de|a) la manana", " ", q)
    for name, i in DAY_NAMES.items():
        if re.search(rf"\b{name}s?\b", q):
            out["days"].append(WEEK[i])
    for m in re.finditer(r"\b(\d{1,2}) de oct", q):
        d = f"2026-10-{int(m.group(1)):02d}"
        if d in WEEK:
            out["days"].append(d)
    if re.search(r"fin de semana", q):
        out["days"] += WEEK[5:]
    if re.search(r"\bhoy\b", q) and today[:10] in WEEK:
        out["days"].append(today[:10])
    if re.search(r"\bmanana\b", q) and today[:10] in WEEK:
        t = (datetime.strptime(today[:10], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        if t in WEEK:
            out["days"].append(t)
    out["days"] = sorted(set(out["days"]))

    if not out["time"]:
        if re.search(r"\bnoche", p):
            out["time"] = "noche"
        elif re.search(r"\btardes?\b", p):
            out["time"] = "tarde"

    for c in cities:
        if c and norm(c) in p:
            out["city"] = c
    if not out["city"]:
        for alias, c in CITY_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", p) and c in cities:
                out["city"] = c
                break

    if re.search(r"presencial", p):
        out["mode"] = "presencial"
    elif re.search(r"\b(virtual|remoto|online|a distancia)\b", p):
        out["mode"] = "virtual"

    out["mode_hard"] = bool(out["mode"] and re.search(r"\b(solo|solamente|unicamente|exclusivamente)\s+(en\s+)?(modalidad\s+)?(presencial|virtual)", p))

    m = re.search(r"\btop\s*(\d+)", p) or re.search(
        r"\b(\d+|un|uno|dos|tres|cuatro|cinco|seis|siete|ocho)\s+(?:mejores|eventos|opciones|recomendaciones)", p
    )
    if m:
        v = m.group(1)
        n = int(v) if v.isdigit() else NUM.get(v)
        if n:
            out["top_n"] = max(1, min(12, n))

    out["goals"] = [g for g, rx in GOALS.items() if re.search(rx, p)]
    return out


LOGISTICS_RX = re.compile(
    r"\b(vivo|estoy|ubicad[oa]|resido|trabajo)\s+en\s+[a-z ]{3,25}|\bpor las (tardes?|noches?|mananas?)\b|\b(solo |prefiero |quiero )?(presencial(es)?|virtual(es)?|online|remoto)\b|"
    r"\b(gratis|gratuit[oa]s?)\b|\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo)s?\b|\bfin de semana\b|\btop\s*\d+\b"
)


def semantic_query(prompt: str, cities: list[str]) -> str:
    """Quita lugar, horario y formato del texto: eso lo evalúa la logística, no el significado."""
    q = norm(prompt)
    q = LOGISTICS_RX.sub(" ", q)
    for c in list(cities) + list(CITY_ALIASES):
        q = re.sub(rf"\b{re.escape(norm(c))}\b", " ", q)
    q = re.sub(r"\s+", " ", q).strip(" ,.;")
    return q if len(q) >= 15 else prompt


def keywords(prompt: str) -> list[str]:
    seen, out = set(), []
    for w in re.findall(r"[a-z0-9]+", norm(prompt)):
        if len(w) >= 4 and w not in STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out


# ---------------------------------------------------------------- señales del evento
def _hits(text: str, name: str, goal: str) -> list[str]:
    found = []
    for kw in SIGNALS[goal]:
        rx = re.compile(rf"(?<![a-z0-9]){re.escape(kw)}")
        if rx.search(name) or rx.search(text):
            found.append(kw)
    return found


def goal_score(ev: dict, goal: str) -> tuple[float, list[str]]:
    name, text = norm(ev["name"]), norm(ev["description"][:700])
    hits = _hits(text, name, goal)
    in_name = sum(1 for k in hits if re.search(rf"(?<![a-z0-9]){re.escape(k)}", name))
    return min(1.0, (in_name * 1.0 + (len(hits) - in_name) * 0.5) / 2), hits[:4]


def overlap(ev: dict, kws: list[str]) -> list[str]:
    stems = {_stem(w) for w in re.findall(r"[a-z0-9]+", norm(ev["name"] + " " + ev["description"] + " " + " ".join(ev["hosts"])))}
    return [k for k in kws if _stem(k) in stems][:6]


# ---------------------------------------------------------------- búsqueda
def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def search(
    prompt: str,
    days: list[str] | None = None,
    city: str | None = None,
    mode: str | None = None,
    include_soldout: bool = True,
    hide_ended: bool = True,
    top_n: int | None = None,
) -> dict:
    t0 = time.perf_counter()
    events = load_events()
    cities = sorted({e["city"] for e in events.values() if e["city"]})
    now = now_lima()
    intent = parse_intent(prompt, cities, now)

    ui_days = [d for d in (days or []) if d in WEEK]
    eff_days = intent["days"] or (ui_days if 0 < len(ui_days) < 7 else [])
    top_n = top_n or intent["top_n"] or 5
    kws = keywords(prompt)

    # --- prefiltros (se ejecutan dentro de LanceDB)
    where = []
    if hide_ended:
        where.append(f"`end` >= {_sql_str(now)}")
    if eff_days:
        where.append(
            "(" + " OR ".join(f"(`start` <= {_sql_str(d + ' 23:59')} AND `end` >= {_sql_str(d + ' 00:00')})" for d in eff_days) + ")"
        )
    if not include_soldout:
        where.append("status = 'abierto'")
    if not mode and intent["mode_hard"]:
        mode = intent["mode"]  # "solo virtual" en el texto se trata como filtro, no como preferencia
    if mode:
        where.append(f"mode = {_sql_str(mode)}")
    if city:
        where.append(f"city = {_sql_str(city)}")

    sem_q = semantic_query(prompt, cities)
    qvec = embed([sem_q])[0]
    tbl = table()
    q = tbl.search(qvec).metric("cosine")
    if where:
        q = q.where(" AND ".join(where), prefilter=True)
    rows = q.limit(2000).to_list()
    best: dict[str, dict] = {}
    for r in rows:
        sim = 1 - float(r["_distance"])
        if r["event_id"] not in best or sim > best[r["event_id"]]["sim"]:
            best[r["event_id"]] = {"sim": sim, "body": r["body"]}

    # --- pesos que se adaptan a la petición
    w = dict(W_BASE)
    goals = intent["goals"]
    has_log = bool(intent["days"] or intent["time"] or intent["city"] or intent["mode"])
    if not goals:
        w["semantica"] += w["objetivo"]
        w["objetivo"] = 0
    if has_log:
        w["logistica"] = 15
        w["semantica"] -= 5
    else:
        w["semantica"] += w["logistica"]
        w["logistica"] = 0
    if "networking" in goals:
        w["escala"] += 3
        w["semantica"] -= 3
    if "empleo" in goals:
        w["objetivo"] += 3
        w["semantica"] -= 3
    total_w = sum(w.values())
    w = {k: round(v * 100 / total_w) for k, v in w.items()}

    sims = [b["sim"] for b in best.values()] or [0]
    lo, hi = min(sims), max(sims)

    scored = []
    for eid, b in best.items():
        ev = events[eid]
        s, trace = {}, []
        # semántica
        absn = max(0.0, min(1.0, (b["sim"] - 0.10) / 0.50)) * 10
        rel = (b["sim"] - lo) / (hi - lo) * 10 if hi > lo else absn
        s["semantica"] = round(0.5 * absn + 0.5 * rel, 1)
        common = overlap(ev, kws)
        trace.append(
            (
                "SEM",
                s["semantica"],
                f"Similitud vectorial {b['sim']:.2f} con un fragmento del evento."
                + (
                    f" Palabras tuyas que aparecen en él: {', '.join(common)}."
                    if common
                    else " No comparte palabras literales con tu texto; la afinidad es de significado."
                ),
            )
        )
        # objetivo
        if goals:
            parts, vals = [], []
            for g in goals:
                v, hits = goal_score(ev, g)
                vals.append(v)
                parts.append(f"{GOAL_LABEL[g].lower()}: " + (", ".join(hits) if hits else "sin señales claras"))
            s["objetivo"] = round(10 * sum(vals) / len(vals), 1)
            trace.append(("OBJ", s["objetivo"], "Señales por objetivo → " + "; ".join(parts) + "."))
        else:
            s["objetivo"] = 0
        # disponibilidad
        ended = ev["end"] < now
        started = ev["start"] <= now < ev["end"]
        spots = ev["spots"]
        if ended:
            s["disponibilidad"] = 0
            msg = "Ya terminó."
        elif ev["status"] == "agotado":
            s["disponibilidad"] = 0.5
            msg = "Agotado: no hay cupos."
        elif ev["status"] == "lista de espera":
            s["disponibilidad"] = 3
            msg = "Solo lista de espera: entrarías si alguien libera cupo."
        else:
            s["disponibilidad"] = 8 if ev["approval"] else 10
            msg = (
                "Abierto" + (f" con {spots} cupos" if spots else "") + (", requiere aprobación del organizador." if ev["approval"] else ".")
            )
            if spots is not None and spots <= 10:
                s["disponibilidad"] = min(s["disponibilidad"], 6)
                msg += " Quedan pocos cupos."
        if started:
            s["disponibilidad"] = max(0, s["disponibilidad"] - 2)
            msg += " Ya empezó."
        trace.append(("DISP", s["disponibilidad"], msg))
        # escala
        g = ev["guests"]
        if g:
            s["escala"] = round(min(10, 10 * math.log1p(g) / math.log1p(500)), 1)
            trace.append(
                (
                    "ESC",
                    s["escala"],
                    f"{g} inscritos hasta ahora: "
                    + (
                        "comunidad grande, más contactos posibles."
                        if g >= 200
                        else "grupo mediano."
                        if g >= 60
                        else "grupo pequeño, trato más directo."
                    ),
                )
            )
        else:
            s["escala"] = 4
            trace.append(("ESC", 4, "El organizador no muestra inscritos; no puedo estimar el tamaño."))
        # logística
        lg, notes = 10.0, []
        hour = int(ev["start"][11:13])
        long_span = (datetime.strptime(ev["end"], FMT) - datetime.strptime(ev["start"], FMT)) > timedelta(hours=30)
        if intent["time"]:
            ok = {"mañana": hour < 12, "tarde": 12 <= hour < 19, "noche": hour >= 17}[intent["time"]]
            if ok:
                notes.append(f"empieza {ev['start'][11:]}, cuadra con tu horario de {intent['time']}")
            else:
                lg -= 3
                notes.append(f"empieza {ev['start'][11:]}, no es en la {intent['time']} que pediste")
        if intent["city"]:
            if ev["mode"] == "virtual":
                lg -= 2
                notes.append("es virtual: sin traslado")
            elif ev["city"] == intent["city"]:
                notes.append(f"es en {ev['city']}, tu zona")
            elif ev["city"] in OUTSIDE_LIMA and intent["city"] not in OUTSIDE_LIMA:
                lg -= 8
                notes.append(f"es en {ev['city']}, fuera de Lima: requiere viaje")
            elif ev["city"]:
                lg -= 3
                notes.append(f"es en {ev['city']}, no en {intent['city']}")
            else:
                lg -= 3
                notes.append("ubicación por confirmar")
        if intent["mode"] and ev["mode"] != intent["mode"]:
            lg -= 5
            notes.append(f"es {ev['mode']} y prefieres {intent['mode']}")
        if long_span:
            notes.append("es una serie de varios días")
        s["logistica"] = max(0.0, lg)
        if has_log or notes:
            trace.append(
                ("LOG", s["logistica"], (("; ".join(notes)[:1].upper() + "; ".join(notes)[1:] + ".") if notes else "Sin restricciones."))
            )
        total = sum(w[k] * s[k] for k in w) / 100 * 10
        scored.append(
            {"ev": ev, "scores": s, "trace": trace, "total": round(total, 1), "sim": b["sim"], "body": b["body"], "common": common}
        )

    scored.sort(key=lambda x: -x["total"])
    top = scored[:top_n]

    # --- conflictos de horario
    conflicts = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            a, b = top[i]["ev"], top[j]["ev"]
            span = lambda e: datetime.strptime(e["end"], FMT) - datetime.strptime(e["start"], FMT) > timedelta(hours=30)
            if not span(a) and not span(b) and a["start"] < b["end"] and b["start"] < a["end"]:
                conflicts.append({"a": a["name"], "b": b["name"], "day": day_label(a["start"][:10])})

    # --- por qué quedaron fuera los más cercanos semánticamente
    cut = top[-1]["total"] if top else 0
    chosen = {t["ev"]["id"] for t in top}
    full = tbl.search(qvec).metric("cosine").limit(2000).to_list()
    near: dict[str, float] = {}
    for r in full:
        near[r["event_id"]] = max(near.get(r["event_id"], -1), 1 - float(r["_distance"]))
    excluded = []
    for eid, sim in sorted(near.items(), key=lambda kv: -kv[1])[:14]:
        if eid in chosen:
            continue
        ev = events[eid]
        reason = None
        if hide_ended and ev["end"] < now:
            reason = "Ya terminó."
        elif eid not in best:
            if eff_days and not any(ev["start"][:10] <= d <= ev["end"][:10] for d in eff_days):
                reason = f"Es el {day_label(ev['start'][:10])}, fuera de los días que pediste."
            elif not include_soldout and ev["status"] != "abierto":
                reason = f"Está {ev['status']} y ocultaste esos eventos."
            elif mode and ev["mode"] != mode:
                reason = f"Es {ev['mode']} y filtraste por {mode}."
            elif city and ev["city"] != city:
                reason = f"Es en {ev['city'] or 'ubicación por confirmar'} y filtraste por {city}."
            else:
                reason = "No pasó los filtros."
        else:
            sc = next((x for x in scored if x["ev"]["id"] == eid), None)
            if sc:
                weakest = min((k for k in w if w[k]), key=lambda k: sc["scores"][k])
                reason = f"Parecido a lo que escribiste (similitud {sim:.2f}) pero sumó {sc['total']:.0f}/100, bajo el corte de {cut:.0f}. Su punto más débil: {CRIT_LABEL[weakest].lower()} ({sc['scores'][weakest]}/10)."
        if reason:
            excluded.append({"event": ev, "sim": round(sim, 2), "reason": reason})
        if len(excluded) >= 5:
            break

    def fmt_intent():
        lines = []
        if intent["goals"]:
            lines.append("Objetivos: " + ", ".join(GOAL_LABEL[g] for g in intent["goals"]))
        else:
            lines.append("Objetivos: no detecté ninguno explícito; busco solo por afinidad de significado")
        if eff_days:
            lines.append(
                "Días: " + ", ".join(day_label(d) for d in eff_days) + (" (de tu texto)" if intent["days"] else " (de los filtros)")
            )
        if intent["time"]:
            lines.append(f"Horario preferido: {intent['time']}")
        if city or intent["city"]:
            lines.append(f"Zona: {city or intent['city']}" + (" (filtro)" if city else " (preferencia)"))
        if mode or intent["mode"]:
            lines.append(f"Formato: {mode or intent['mode']}" + (" (filtro)" if mode else " (preferencia)"))
        lines.append(f"Mostrando {top_n} eventos" + (" (lo pediste en tu texto)" if intent["top_n"] else ""))
        return lines

    return {
        "now": now,
        "low_confidence": bool(top) and max(t["sim"] for t in top) < 0.40,
        "semantic_query": sem_q,
        "interpretation": fmt_intent(),
        "weights": [{"key": k, "label": CRIT_LABEL[k], "weight": w[k]} for k in w if w[k]],
        "candidates": len(best),
        "results": [
            {
                "event": t["ev"],
                "total": t["total"],
                "scores": t["scores"],
                "sim": round(t["sim"], 3),
                "snippet": (t["body"][:260] + ("…" if len(t["body"]) > 260 else "")) if t["body"] else "",
                "keywords": t["common"],
                "trace": [{"tag": a, "score": b, "text": c} for a, b, c in t["trace"]],
            }
            for t in top
        ],
        "excluded": excluded,
        "conflicts": conflicts,
        "ms": round((time.perf_counter() - t0) * 1000),
    }
