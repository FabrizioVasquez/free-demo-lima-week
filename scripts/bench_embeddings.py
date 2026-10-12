"""Compara modelos de embeddings sobre 15 consultas con respuesta conocida: calidad (hit@k, MRR), latencia y memoria.
uso: uv run python scripts/bench_embeddings.py sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
     uv run python scripts/bench_embeddings.py minishlab/potion-multilingual-128M"""
import json
import resource
import statistics
import sys
import time

import numpy as np

from brujula.embed import tokenizer
from brujula.index import chunks_of

TOK = tokenizer()
model_name = sys.argv[1]
from fastembed import TextEmbedding

t0 = time.perf_counter(); m = TextEmbedding(model_name=model_name, cache_dir="data/models"); list(m.embed(["warmup"])); load = time.perf_counter() - t0
events = json.load(open("data/events.json"))
rows = [(e["id"], t) for e in events for t, _ in chunks_of(e, TOK)]
t0 = time.perf_counter(); V = np.array(list(m.embed([t for _, t in rows]))); idx_s = time.perf_counter() - t0
V /= np.linalg.norm(V, axis=1, keepdims=True)
Q = {
 "quiero un hackathon para construir agentes de IA": ["Hack AI Agents","Hack the Andes","Hackathon Transforma","Quantum Computing","AGROTECH","Sunass","IAthon"],
 "stablecoins y pagos internacionales": ["pagos internacionales","Blockchain es Clave","Stellar"],
 "computación cuántica": ["Quantum Computing","AI Salon"],
 "salud mental y bienestar con inteligencia artificial": ["forHuman","HealthTech","Salud","Conecta Científica"],
 "networking para mujeres líderes en tecnología": ["Women","ELLA LIDERA","Warmi","Female"],
 "cómo levantar capital con inversionistas de venture capital": ["Fundraising","Venture Capital","Warmi","Equity","Founders & VCs","Mixer"],
 "videojuegos y desarrollo de juegos": ["videojuegos"],
 "marketing digital con IA": ["MARKETING","AI Growth","Linkedin"],
 "construcción e inmobiliaria con tecnología": ["Construction","Construcción"],
 "gestión de producto y UX": ["PRODUCT FEST"],
 "robótica para niños": ["RoboThink"],
 "agricultura y agro": ["AGROTECH"],
 "gobierno y ciudades inteligentes": ["GovTech","CivicTech"],
 "educación edtech": ["EDTECH","Despegue"],
 "crear una startup global y cobrar con Stripe": ["Stripe","Legal Launchpad","Blueprint"],
}
name_of = {e["id"]: e["name"] for e in events}
lat, ranks = [], []
for q, exp in Q.items():
    t0 = time.perf_counter(); qv = np.array(list(m.embed([q])))[0]; lat.append((time.perf_counter() - t0) * 1000)
    qv /= np.linalg.norm(qv); sims = V @ qv
    best = {}
    for (eid, _), s in zip(rows, sims, strict=True): best[eid] = max(best.get(eid, -1), s)
    order = [e for e, _ in sorted(best.items(), key=lambda kv: -kv[1])]
    r = next((i + 1 for i, e in enumerate(order) if any(x.lower() in name_of[e].lower() for x in exp)), 999)
    ranks.append(r)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # macOS: bytes
print(json.dumps({"model": model_name.split("/")[-1], "dim": int(V.shape[1]), "load_s": round(load, 2), "index_all_s": round(idx_s, 2),
  "query_ms_median": round(statistics.median(lat), 1), "peak_rss_MB": round(rss), "hit@1": sum(r <= 1 for r in ranks), "hit@3": sum(r <= 3 for r in ranks),
  "hit@5": sum(r <= 5 for r in ranks), "of": len(Q), "MRR": round(sum(1 / r for r in ranks) / len(ranks), 3), "ranks": ranks}))
