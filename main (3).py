"""
BioAI - Genomics Research Assistant
FastAPI backend with NCBI E-utilities integration, DNA analysis, and Gemini AI.
"""
import os
import re
import json
import time
import sqlite3
import uuid
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ============================================================================
# CONFIG
# ============================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_KEY_HERE")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "bioai@example.com")
NCBI_TOOL = "BioAI"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bioai_cache.db")

# ============================================================================
# ORGANISMS
# ============================================================================
ORGANISMS = {
    "drosophila": {
        "key": "drosophila",
        "scientific_name": "Drosophila melanogaster",
        "common_name": "Fruit fly",
        "tax_id": "7227",
        "genome_size_mb": 143.7,
        "gc_percent": 42.0,
        "chromosomes": "4 (X, Y, 2, 3, 4)",
        "gene_count": "~14,000",
        "description": "A small fly used in genetics for over a century. Classic model for development, behavior, and disease genes.",
        "key_genes": ["white", "Antp", "bcd", "wg", "hb", "ftz", "eve", "Ubx", "abd-A", "sevenless"],
        "popular_accessions": [
            {"acc": "NM_001275660", "label": "white gene mRNA"},
            {"acc": "NM_079617", "label": "Antennapedia mRNA"},
            {"acc": "NM_169973", "label": "bicoid mRNA"}
        ]
    },
    "mouse": {
        "key": "mouse",
        "scientific_name": "Mus musculus",
        "common_name": "House mouse",
        "tax_id": "10090",
        "genome_size_mb": 2730.0,
        "gc_percent": 42.0,
        "chromosomes": "20 (19 + X/Y)",
        "gene_count": "~22,000",
        "description": "The premier mammalian model for human disease, immunology, neuroscience, and development.",
        "key_genes": ["Trp53", "Brca1", "Sox2", "Oct4", "Nanog", "Myc", "Hoxa1", "Shh", "Pax6", "Apoe"],
        "popular_accessions": [
            {"acc": "NM_011640", "label": "Trp53 mRNA"},
            {"acc": "NM_009741", "label": "Bcl2 mRNA"},
            {"acc": "NM_013684", "label": "Tbp mRNA"}
        ]
    },
    "agrobacterium": {
        "key": "agrobacterium",
        "scientific_name": "Agrobacterium tumefaciens",
        "common_name": "Crown gall bacterium",
        "tax_id": "358",
        "genome_size_mb": 5.67,
        "gc_percent": 59.4,
        "chromosomes": "1 circular + 1 linear chromosome + plasmids (Ti, At)",
        "gene_count": "~5,400",
        "description": "Plant pathogen and the workhorse of plant genetic engineering. The Ti plasmid transfers DNA into plant cells.",
        "key_genes": ["virA", "virB", "virD2", "virE2", "virG", "iaaM", "iaaH", "ipt", "tms1", "tms2"],
        "popular_accessions": [
            {"acc": "AE007869", "label": "C58 chromosome"},
            {"acc": "AE007871", "label": "Ti plasmid pTiC58"},
            {"acc": "X00493", "label": "virD2 region"}
        ]
    },
    "yeast": {
        "key": "yeast",
        "scientific_name": "Saccharomyces cerevisiae",
        "common_name": "Baker's yeast",
        "tax_id": "4932",
        "genome_size_mb": 12.1,
        "gc_percent": 38.3,
        "chromosomes": "16",
        "gene_count": "~6,000",
        "description": "First eukaryote with a fully sequenced genome. Foundation of cell-cycle, metabolism, and aging research.",
        "key_genes": ["GAL1", "GAL4", "ACT1", "TUB1", "CDC28", "RAD51", "TOR1", "SIR2", "URA3", "LEU2"],
        "popular_accessions": [
            {"acc": "NM_001178160", "label": "GAL1 mRNA"},
            {"acc": "NM_001178208", "label": "ACT1 mRNA"},
            {"acc": "NM_001183480", "label": "CDC28 mRNA"}
        ]
    },
    "xenopus": {
        "key": "xenopus",
        "scientific_name": "Xenopus laevis",
        "common_name": "African clawed frog",
        "tax_id": "8355",
        "genome_size_mb": 3100.0,
        "gc_percent": 40.5,
        "chromosomes": "36 (allotetraploid)",
        "gene_count": "~45,000",
        "description": "Premier vertebrate embryology model. Large eggs that develop externally make it ideal for studying early development.",
        "key_genes": ["nodal", "goosecoid", "chordin", "noggin", "siamois", "Xbra", "Xnr1", "Vg1", "Mix.1", "Sox17"],
        "popular_accessions": [
            {"acc": "NM_001088134", "label": "chordin mRNA"},
            {"acc": "NM_001087230", "label": "noggin mRNA"},
            {"acc": "NM_001087380", "label": "goosecoid mRNA"}
        ]
    }
}

ORG_NAME_PATTERNS = {
    "drosophila": ["drosophila", "fruit fly", "fruitfly", "d. melanogaster", "d melanogaster", "melanogaster"],
    "mouse": ["mouse", "mice", "murine", "mus musculus", "m. musculus", "m musculus"],
    "agrobacterium": ["agrobacterium", "crown gall", "tumefaciens", "a. tumefaciens"],
    "yeast": ["yeast", "saccharomyces", "s. cerevisiae", "cerevisiae", "baker's yeast", "bakers yeast"],
    "xenopus": ["xenopus", "frog", "x. laevis", "laevis", "clawed frog"]
}

# ============================================================================
# DATABASE (cache only)
# ============================================================================
def db_init():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ncbi_cache (
            cache_key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            cached_at REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def cache_get(key: str, ttl_seconds: int) -> Optional[Any]:
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT data, cached_at FROM ncbi_cache WHERE cache_key=?", (key,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        data, cached_at = row
        if time.time() - cached_at > ttl_seconds:
            return None
        return json.loads(data)
    except Exception:
        return None

def cache_set(key: str, value: Any):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO ncbi_cache(cache_key, data, cached_at) VALUES(?, ?, ?)",
            (key, json.dumps(value), time.time())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

# ============================================================================
# GENETIC CODE
# ============================================================================
GENETIC_CODE = {
    "TTT": "Phe", "TTC": "Phe", "TTA": "Leu", "TTG": "Leu",
    "CTT": "Leu", "CTC": "Leu", "CTA": "Leu", "CTG": "Leu",
    "ATT": "Ile", "ATC": "Ile", "ATA": "Ile", "ATG": "Met",
    "GTT": "Val", "GTC": "Val", "GTA": "Val", "GTG": "Val",
    "TCT": "Ser", "TCC": "Ser", "TCA": "Ser", "TCG": "Ser",
    "CCT": "Pro", "CCC": "Pro", "CCA": "Pro", "CCG": "Pro",
    "ACT": "Thr", "ACC": "Thr", "ACA": "Thr", "ACG": "Thr",
    "GCT": "Ala", "GCC": "Ala", "GCA": "Ala", "GCG": "Ala",
    "TAT": "Tyr", "TAC": "Tyr", "TAA": "STOP", "TAG": "STOP",
    "CAT": "His", "CAC": "His", "CAA": "Gln", "CAG": "Gln",
    "AAT": "Asn", "AAC": "Asn", "AAA": "Lys", "AAG": "Lys",
    "GAT": "Asp", "GAC": "Asp", "GAA": "Glu", "GAG": "Glu",
    "TGT": "Cys", "TGC": "Cys", "TGA": "STOP", "TGG": "Trp",
    "CGT": "Arg", "CGC": "Arg", "CGA": "Arg", "CGG": "Arg",
    "AGT": "Ser", "AGC": "Ser", "AGA": "Arg", "AGG": "Arg",
    "GGT": "Gly", "GGC": "Gly", "GGA": "Gly", "GGG": "Gly"
}

AA_3TO1 = {
    "Ala":"A","Arg":"R","Asn":"N","Asp":"D","Cys":"C","Gln":"Q","Glu":"E","Gly":"G",
    "His":"H","Ile":"I","Leu":"L","Lys":"K","Met":"M","Phe":"F","Pro":"P","Ser":"S",
    "Thr":"T","Trp":"W","Tyr":"Y","Val":"V","STOP":"*"
}

AA_PROPERTIES = {
    "Ala": "small/hydrophobic", "Val": "small/hydrophobic", "Leu": "hydrophobic",
    "Ile": "hydrophobic", "Pro": "hydrophobic/rigid", "Phe": "aromatic/hydrophobic",
    "Met": "hydrophobic/start", "Trp": "aromatic/hydrophobic",
    "Gly": "small/flexible", "Ser": "polar", "Thr": "polar", "Cys": "polar/disulfide",
    "Tyr": "aromatic/polar", "Asn": "polar", "Gln": "polar",
    "Lys": "positive", "Arg": "positive", "His": "positive/weak",
    "Asp": "negative", "Glu": "negative",
    "STOP": "termination"
}

def clean_dna(seq: str) -> str:
    if not seq:
        return ""
    return re.sub(r"[^ATGCUatgcu]", "", seq).upper().replace("U", "T")

def reverse_complement(seq: str) -> str:
    comp = {"A":"T","T":"A","G":"C","C":"G","N":"N"}
    return "".join(comp.get(b, "N") for b in reversed(seq.upper()))

def translate_dna(seq: str) -> Dict[str, Any]:
    s = clean_dna(seq)
    n = len(s)
    if n == 0:
        return {"error": "no valid DNA"}
    codons = []
    aa_list_3 = []
    aa_list_1 = []
    has_stop = False
    for i in range(0, n - (n % 3), 3):
        codon = s[i:i+3]
        aa3 = GENETIC_CODE.get(codon, "Xaa")
        codons.append(codon)
        aa_list_3.append(aa3)
        aa_list_1.append(AA_3TO1.get(aa3, "X"))
        if aa3 == "STOP":
            has_stop = True
    g = s.count("G"); c = s.count("C"); a = s.count("A"); t = s.count("T")
    gc = (g + c) / n * 100 if n else 0
    at = (a + t) / n * 100 if n else 0
    aa_props = {}
    for aa3 in aa_list_3:
        if aa3 != "STOP":
            aa_props[aa3] = AA_PROPERTIES.get(aa3, "?")
    return {
        "sequence": s,
        "dna_length": n,
        "gc_content": round(gc, 2),
        "at_content": round(at, 2),
        "codons": codons,
        "protein_3letter": "-".join(aa_list_3),
        "protein_1letter": "".join(aa_list_1),
        "protein_length": len([a for a in aa_list_3 if a != "STOP"]),
        "has_stop": has_stop,
        "starts_met": aa_list_3[0] == "Met" if aa_list_3 else False,
        "aa_properties": aa_props
    }

def detect_mutations(ref: str, sample: str) -> Dict[str, Any]:
    r = clean_dna(ref); s = clean_dna(sample)
    L = max(len(r), len(s))
    if L == 0:
        return {"error": "no valid sequences"}
    r_pad = r.ljust(L, "-"); s_pad = s.ljust(L, "-")
    subs = 0; ins = 0; dels = 0; matches = 0
    mutations = []
    for i in range(L):
        if r_pad[i] == s_pad[i]:
            matches += 1
        elif r_pad[i] == "-":
            ins += 1
            mutations.append({"position": i+1, "type": "insertion",
                              "description": f"insertion of {s_pad[i]} at position {i+1}"})
        elif s_pad[i] == "-":
            dels += 1
            mutations.append({"position": i+1, "type": "deletion",
                              "description": f"deletion of {r_pad[i]} at position {i+1}"})
        else:
            subs += 1
            mutations.append({"position": i+1, "type": "substitution",
                              "description": f"{r_pad[i]} -> {s_pad[i]} at position {i+1}"})
    identity = matches / L * 100 if L else 0
    aa_changes = []
    if abs(len(r) - len(s)) % 3 == 0:
        ref_t = translate_dna(r).get("protein_3letter", "").split("-") if r else []
        sam_t = translate_dna(s).get("protein_3letter", "").split("-") if s else []
        m = min(len(ref_t), len(sam_t))
        for i in range(m):
            if ref_t[i] != sam_t[i] and ref_t[i] and sam_t[i]:
                effect = "missense"
                if sam_t[i] == "STOP" and ref_t[i] != "STOP":
                    effect = "stop_gained"
                elif ref_t[i] == "STOP" and sam_t[i] != "STOP":
                    effect = "stop_lost"
                elif ref_t[i] == sam_t[i]:
                    effect = "synonymous"
                aa_changes.append({
                    "position": i+1,
                    "ref_aa": ref_t[i],
                    "alt_aa": sam_t[i],
                    "effect": effect
                })
    return {
        "identity_pct": round(identity, 2),
        "total_mutations": len(mutations),
        "substitutions": subs,
        "insertions": ins,
        "deletions": dels,
        "mutations": mutations[:50],
        "aa_changes": aa_changes[:50]
    }

def gc_analysis(seq: str) -> Dict[str, Any]:
    s = clean_dna(seq)
    n = len(s)
    if n == 0:
        return {"error": "no valid DNA"}
    g = s.count("G"); c = s.count("C"); a = s.count("A"); t = s.count("T")
    gc = (g + c) / n * 100
    at = (a + t) / n * 100
    win = max(20, n // 30)
    sliding = []
    for i in range(0, n - win + 1, max(1, win // 2)):
        chunk = s[i:i+win]
        cn = len(chunk)
        if cn:
            sliding.append(round((chunk.count("G") + chunk.count("C")) / cn * 100, 2))
    return {
        "gc_pct": round(gc, 2),
        "at_pct": round(at, 2),
        "counts": {"A": a, "T": t, "G": g, "C": c},
        "length": n,
        "sliding_gc": sliding[:60]
    }

# ============================================================================
# NCBI E-UTILITIES
# ============================================================================
def _ncbi_params(extra: Dict[str, str]) -> Dict[str, str]:
    p = {"tool": NCBI_TOOL, "email": NCBI_EMAIL}
    if NCBI_API_KEY:
        p["api_key"] = NCBI_API_KEY
    p.update(extra)
    return p

async def ncbi_get(client: httpx.AsyncClient, path: str, params: Dict[str, str]) -> str:
    url = f"{NCBI_BASE}/{path}"
    p = _ncbi_params(params)
    r = await client.get(url, params=p, timeout=25.0)
    r.raise_for_status()
    return r.text

async def esearch(client: httpx.AsyncClient, db: str, term: str, retmax: int = 10) -> List[str]:
    text = await ncbi_get(client, "esearch.fcgi", {
        "db": db, "term": term, "retmax": str(retmax), "retmode": "json"
    })
    try:
        data = json.loads(text)
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception:
        return []

async def esummary(client: httpx.AsyncClient, db: str, ids: List[str]) -> Dict[str, Any]:
    if not ids:
        return {}
    text = await ncbi_get(client, "esummary.fcgi", {
        "db": db, "id": ",".join(ids), "retmode": "json"
    })
    try:
        data = json.loads(text)
        return data.get("result", {})
    except Exception:
        return {}

async def elink(client: httpx.AsyncClient, dbfrom: str, db: str, ids: List[str], linkname: str = "") -> List[str]:
    if not ids:
        return []
    params = {"dbfrom": dbfrom, "db": db, "id": ",".join(ids), "retmode": "json"}
    if linkname:
        params["linkname"] = linkname
    text = await ncbi_get(client, "elink.fcgi", params)
    try:
        data = json.loads(text)
        linksets = data.get("linksets", [])
        out = []
        for ls in linksets:
            for ld in ls.get("linksetdbs", []):
                out.extend(ld.get("links", []))
        seen = set(); res = []
        for x in out:
            if x not in seen:
                seen.add(x); res.append(str(x))
        return res
    except Exception:
        return []

async def efetch(client: httpx.AsyncClient, db: str, ids: List[str], rettype: str, retmode: str = "text") -> str:
    if not ids:
        return ""
    return await ncbi_get(client, "efetch.fcgi", {
        "db": db, "id": ",".join(ids), "rettype": rettype, "retmode": retmode
    })

# ============================================================================
# GENBANK PARSER
# ============================================================================
def parse_genbank_multi(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    records = re.split(r"^//\s*$", text, flags=re.MULTILINE)
    out = []
    for raw in records:
        raw = raw.strip()
        if not raw or "LOCUS" not in raw:
            continue
        rec: Dict[str, Any] = {
            "accession": "", "definition": "", "organism": "",
            "mol_type": "", "length": 0, "cds_list": [],
            "exon_count": 0, "sequence_preview": ""
        }
        m = re.search(r"^ACCESSION\s+(\S+)", raw, re.MULTILINE)
        if m: rec["accession"] = m.group(1)
        m = re.search(r"^LOCUS\s+\S+\s+(\d+)\s+bp\s+(\S+)", raw, re.MULTILINE)
        if m:
            rec["length"] = int(m.group(1))
            rec["mol_type"] = m.group(2)
        m = re.search(r"^DEFINITION\s+(.+?)(?=^\S)", raw + "\n", re.MULTILINE | re.DOTALL)
        if m:
            rec["definition"] = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".")
        m = re.search(r"ORGANISM\s+(.+)", raw)
        if m:
            rec["organism"] = m.group(1).strip()
        m = re.search(r'/mol_type="([^"]+)"', raw)
        if m and not rec["mol_type"]:
            rec["mol_type"] = m.group(1)
        rec["exon_count"] = len(re.findall(r"^\s{5}exon\s+", raw, re.MULTILINE))
        cds_blocks = re.findall(r"^\s{5}CDS\s+(\S.*?)(?=^\s{5}\S|^ORIGIN|\Z)", raw, re.MULTILINE | re.DOTALL)
        for cb in cds_blocks[:5]:
            cds: Dict[str, Any] = {}
            loc_match = re.match(r"(\S+(?:\s|$))", cb)
            if loc_match:
                cds["location"] = loc_match.group(1).strip()
            mp = re.search(r'/product="([^"]+)"', cb)
            if mp: cds["product"] = mp.group(1).replace("\n", " ").strip()
            mpid = re.search(r'/protein_id="([^"]+)"', cb)
            if mpid: cds["protein_id"] = mpid.group(1)
            mg = re.search(r'/gene="([^"]+)"', cb)
            if mg: cds["gene"] = mg.group(1)
            mt = re.search(r'/translation="([^"]+)"', cb, re.DOTALL)
            if mt:
                tr = re.sub(r"\s+", "", mt.group(1))
                cds["translation"] = tr[:80]
                cds["protein_length"] = len(tr)
            rec["cds_list"].append(cds)
        origin = re.search(r"^ORIGIN(.*?)(?=^//|\Z)", raw, re.MULTILINE | re.DOTALL)
        if origin:
            seq = re.sub(r"[^ATGCNatgcn]", "", origin.group(1))[:200].upper()
            rec["sequence_preview"] = seq
        out.append(rec)
    return out

def parse_fasta_protein(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    lines = text.strip().splitlines()
    if not lines or not lines[0].startswith(">"):
        return {}
    header = lines[0][1:].strip()
    seq = "".join(l.strip() for l in lines[1:] if not l.startswith(">"))
    parts = header.split(" ", 1)
    return {
        "accession": parts[0],
        "definition": parts[1] if len(parts) > 1 else "",
        "type": "protein",
        "length": len(seq),
        "sequence_preview": seq[:200]
    }

# ============================================================================
# NCBI HIGH-LEVEL
# ============================================================================
async def fetch_gene_full(organism_key: str, gene_name: str) -> Dict[str, Any]:
    org = ORGANISMS.get(organism_key)
    if not org:
        return {"error": "unknown organism"}
    cache_key = f"gene::{organism_key}::{gene_name.lower()}"
    cached = cache_get(cache_key, 86400)
    if cached:
        return cached
    async with httpx.AsyncClient() as client:
        term = f'{gene_name}[Gene Name] AND {org["tax_id"]}[Taxonomy ID]'
        gene_ids = await esearch(client, "gene", term, retmax=3)
        if not gene_ids:
            return {"error": f"gene '{gene_name}' not found in {org['scientific_name']}"}
        gene_id = gene_ids[0]
        summary = await esummary(client, "gene", [gene_id])
        gdata = summary.get(gene_id, {}) if isinstance(summary, dict) else {}
        result: Dict[str, Any] = {
            "gene_id": gene_id,
            "symbol": gdata.get("name", gene_name),
            "full_name": gdata.get("description", ""),
            "organism": org["scientific_name"],
            "organism_key": organism_key,
            "chromosome": gdata.get("chromosome", ""),
            "location": gdata.get("maplocation", ""),
            "summary": gdata.get("summary", ""),
            "aliases": gdata.get("otheraliases", ""),
            "ncbi_url": f"https://www.ncbi.nlm.nih.gov/gene/{gene_id}",
            "mrna_records": []
        }
        try:
            mrna_ids = await elink(client, "gene", "nuccore", [gene_id], "gene_nuccore_refseqrna")
        except Exception:
            mrna_ids = []
        if mrna_ids:
            top_ids = mrna_ids[:3]
            try:
                gb = await efetch(client, "nuccore", top_ids, "gb", "text")
                result["mrna_records"] = parse_genbank_multi(gb)
                for r in result["mrna_records"]:
                    if r.get("accession"):
                        r["ncbi_url"] = f"https://www.ncbi.nlm.nih.gov/nuccore/{r['accession']}"
            except Exception:
                pass
    cache_set(cache_key, result)
    return result

async def fetch_mrna_records(organism_key: str, gene_name: str, limit: int = 4) -> List[Dict[str, Any]]:
    org = ORGANISMS.get(organism_key)
    if not org:
        return []
    cache_key = f"mrna::{organism_key}::{gene_name.lower()}::{limit}"
    cached = cache_get(cache_key, 43200)
    if cached:
        return cached
    async with httpx.AsyncClient() as client:
        term = f'{gene_name}[Gene Name] AND {org["tax_id"]}[Organism] AND mRNA[Filter] AND RefSeq[Filter]'
        ids = await esearch(client, "nuccore", term, retmax=limit)
        if not ids:
            return []
        try:
            gb = await efetch(client, "nuccore", ids, "gb", "text")
            recs = parse_genbank_multi(gb)
            for r in recs:
                if r.get("accession"):
                    r["ncbi_url"] = f"https://www.ncbi.nlm.nih.gov/nuccore/{r['accession']}"
            cache_set(cache_key, recs)
            return recs
        except Exception:
            return []

async def fetch_accession(accession: str) -> Dict[str, Any]:
    cache_key = f"acc::{accession.upper()}"
    cached = cache_get(cache_key, 172800)
    if cached:
        return cached
    last_err = None
    async with httpx.AsyncClient() as client:
        try:
            gb = await efetch(client, "nuccore", [accession], "gb", "text")
            recs = parse_genbank_multi(gb)
            if recs:
                rec = recs[0]
                rec["type"] = "nucleotide"
                rec["ncbi_url"] = f"https://www.ncbi.nlm.nih.gov/nuccore/{accession}"
                cache_set(cache_key, rec)
                return rec
        except httpx.HTTPStatusError as e:
            last_err = f"NCBI returned HTTP {e.response.status_code}"
        except httpx.TimeoutException:
            last_err = "NCBI request timed out"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
        try:
            fa = await efetch(client, "protein", [accession], "fasta", "text")
            rec = parse_fasta_protein(fa)
            if rec:
                rec["ncbi_url"] = f"https://www.ncbi.nlm.nih.gov/protein/{accession}"
                cache_set(cache_key, rec)
                return rec
        except httpx.HTTPStatusError as e:
            last_err = f"NCBI returned HTTP {e.response.status_code}"
        except httpx.TimeoutException:
            last_err = "NCBI request timed out"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
    if last_err:
        return {"error": f"could not fetch '{accession}': {last_err}"}
    return {"error": f"accession '{accession}' not found"}

# ============================================================================
# INTENT DETECTION
# ============================================================================
DNA_RE = re.compile(r"\b[ATGCUatgcu]{12,}\b")
ACC_RE = re.compile(r"\b([A-Z]{1,2}_?\d{5,9}(?:\.\d+)?)\b")

def detect_organism(text: str) -> Optional[str]:
    t = text.lower()
    for key, patterns in ORG_NAME_PATTERNS.items():
        for p in patterns:
            if p in t:
                return key
    return None

def find_gene_name(text: str) -> Optional[str]:
    m = re.search(r'\bgene\s+["\']?([A-Za-z][A-Za-z0-9\-]{1,15})["\']?', text)
    if m:
        return m.group(1)
    m = re.search(r'\b(?:for|of|the|about)\s+([A-Za-z][A-Za-z0-9\-]{1,15})\s+gene', text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'\b([A-Z][A-Za-z]{1,4}\d+|[A-Z]{2,5})\b', text)
    if m:
        return m.group(1)
    return None

def detect_intent(text: str) -> Dict[str, Any]:
    t = text.lower()
    intents: List[str] = []
    seqs = DNA_RE.findall(text)
    accs = ACC_RE.findall(text)
    if len(seqs) >= 2 or any(k in t for k in ["mutation", "mutations", "compare sequence", "differ"]):
        if len(seqs) >= 2:
            intents.append("mutation_compare")
    if len(seqs) >= 1 and any(k in t for k in ["translate", "translation", "protein from", "amino acid"]):
        intents.append("translate")
    if any(k in t for k in ["reverse complement", "reverse-complement", "revcomp"]):
        if seqs:
            intents.append("reverse_complement")
    if any(k in t for k in ["gc content", "gc%", "gc-content", "gc analysis"]):
        if seqs:
            intents.append("gc_analysis")
    if any(k in t for k in ["mrna", "transcript", "messenger rna", "splice", "isoform"]):
        intents.append("fetch_mrna")
    if "gene" in t or "function" in t or "expressed" in t:
        intents.append("gene_info")
    if any(k in t for k in ["genome", "chromosome", "organism overview", "about the"]):
        intents.append("organism_overview")
    if accs:
        intents.append("fetch_accession")
    seen = set(); out = []
    for i in intents:
        if i not in seen:
            seen.add(i); out.append(i)
    return {"intents": out, "sequences": seqs, "accessions": accs}

# ============================================================================
# AI - GEMINI
# ============================================================================
SYSTEM_PROMPT = """You are BioAI, an expert genomics assistant for students and researchers in molecular biology.

You specialize in 5 model organisms:
- Drosophila melanogaster (fruit fly) - TaxID 7227. Key genes: white, Antp, bcd, wg, hb, eve, Ubx
- Mus musculus (mouse) - TaxID 10090. Key genes: Trp53, Brca1, Sox2, Myc, Hoxa1, Shh, Pax6
- Agrobacterium tumefaciens - TaxID 358. Key genes: virA, virB, virD2, virE2, virG (Ti plasmid)
- Saccharomyces cerevisiae (yeast) - TaxID 4932. Key genes: GAL1, GAL4, ACT1, CDC28, RAD51, TOR1
- Xenopus laevis (frog) - TaxID 8355. Key genes: nodal, goosecoid, chordin, noggin, Xbra

You explain DNA sequences, mRNA structure (5' UTR / CDS / 3' UTR), the central dogma (DNA -> mRNA -> protein),
codon usage, gene function, and genome biology. You translate technical NCBI records into plain English.

TEACHING STYLE: define -> explain -> connect to biology -> real-world relevance. Use concrete examples.

When the message includes "NCBI DATA FOR THIS QUERY": analyze that specific data, reference accession numbers
exactly as given, and provide NCBI URLs from the context. Do NOT invent accessions or sequences.

When local DNA analysis results are provided (translation, mutation, GC), explain what each number means
biologically. Stop codons, GC% extremes, and AA changes all carry meaning - say so.

You CAN answer general biology questions (cell biology, biochemistry, evolution, genetics theory) but
gently redirect off-topic chit-chat back to genomics.

Use markdown: **bold** for key terms, `monospace` for sequences/genes/accessions, headings for sections,
bullet lists for enumerations. Keep responses focused - no padding, no apologies."""

async def call_gemini(history: List[Dict[str, str]], user_msg: str, context: str) -> str:
    if GEMINI_API_KEY in ("", "YOUR_KEY_HERE"):
        return ("**Gemini API key not configured.** Set the `GEMINI_API_KEY` environment variable "
                "(get one free at https://aistudio.google.com/apikey) and restart the server.\n\n"
                "Meanwhile, the NCBI data and local analysis below are still fetched live and accurate.")
    contents = []
    contents.append({"role": "user", "parts": [{"text": SYSTEM_PROMPT}]})
    contents.append({"role": "model", "parts": [{"text": "Understood. I am BioAI, ready to help with genomics."}]})
    for turn in history[-12:]:
        role = "user" if turn.get("role") == "user" else "model"
        text = turn.get("content", "")
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    final_text = user_msg
    if context:
        final_text = f"NCBI DATA FOR THIS QUERY:\n=====\n{context}\n=====\n\nUser question: {user_msg}"
    contents.append({"role": "user", "parts": [{"text": final_text}]})
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048, "topP": 0.95}
    }
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            if r.status_code != 200:
                return f"**Gemini API error** ({r.status_code}): {r.text[:300]}"
            data = r.json()
            cands = data.get("candidates", [])
            if not cands:
                fb = data.get("promptFeedback", {})
                return f"**No response from Gemini.** {json.dumps(fb)[:300]}"
            parts = cands[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts).strip() or "_(empty response)_"
    except httpx.TimeoutException:
        return "**Gemini timed out.** The API took too long. Try again."
    except Exception as e:
        return f"**Gemini call failed:** {type(e).__name__}: {str(e)[:200]}"

# ============================================================================
# PROCESS PIPELINE
# ============================================================================
async def process(message: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    org_key = detect_organism(message)
    if not org_key:
        for turn in reversed(history[-6:]):
            ok = detect_organism(turn.get("content", ""))
            if ok:
                org_key = ok
                break

    intent = detect_intent(message)
    intents = intent["intents"]
    seqs = intent["sequences"]
    accs = intent["accessions"]

    ncbi_data: Dict[str, Any] = {}
    local: Dict[str, Any] = {}
    sources: List[Dict[str, str]] = []
    context_parts: List[str] = []

    if "fetch_accession" in intents and accs:
        acc = accs[0]
        try:
            rec = await fetch_accession(acc)
            ncbi_data["accession_record"] = rec
            if rec.get("ncbi_url"):
                sources.append({"label": rec.get("accession", acc), "url": rec["ncbi_url"]})
            context_parts.append(f"Accession {acc}:\n{json.dumps(rec, indent=2)[:1500]}")
        except Exception as e:
            ncbi_data["accession_error"] = str(e)

    if org_key and ("gene_info" in intents or "fetch_mrna" in intents):
        gene_name = find_gene_name(message)
        if gene_name:
            try:
                if "gene_info" in intents:
                    g = await fetch_gene_full(org_key, gene_name)
                    ncbi_data["gene"] = g
                    if g.get("ncbi_url"):
                        sources.append({"label": f"{g.get('symbol', gene_name)} (gene)", "url": g["ncbi_url"]})
                    context_parts.append(f"Gene record:\n{json.dumps(g, indent=2)[:2000]}")
                if "fetch_mrna" in intents:
                    mrna = await fetch_mrna_records(org_key, gene_name, 4)
                    ncbi_data["mrna_records"] = mrna
                    for m in mrna[:2]:
                        if m.get("ncbi_url"):
                            sources.append({"label": m.get("accession", "mRNA"), "url": m["ncbi_url"]})
                    context_parts.append(f"mRNA records for {gene_name}:\n{json.dumps(mrna, indent=2)[:2000]}")
            except Exception as e:
                ncbi_data["fetch_error"] = str(e)

    if "organism_overview" in intents and org_key:
        ncbi_data["organism"] = ORGANISMS[org_key]
        context_parts.append(f"Organism overview:\n{json.dumps(ORGANISMS[org_key], indent=2)}")

    if "translate" in intents and seqs:
        local["translation"] = translate_dna(seqs[0])
        context_parts.append(f"Translation result:\n{json.dumps(local['translation'], indent=2)[:1000]}")
    if "reverse_complement" in intents and seqs:
        local["reverse_complement"] = {
            "input": clean_dna(seqs[0])[:200],
            "output": reverse_complement(clean_dna(seqs[0]))[:200]
        }
        context_parts.append(f"Reverse complement: {local['reverse_complement']}")
    if "gc_analysis" in intents and seqs:
        local["gc_analysis"] = gc_analysis(seqs[0])
        context_parts.append(f"GC analysis: {json.dumps(local['gc_analysis'])[:500]}")
    if "mutation_compare" in intents and len(seqs) >= 2:
        local["mutations"] = detect_mutations(seqs[0], seqs[1])
        context_parts.append(f"Mutation analysis: {json.dumps(local['mutations'], indent=2)[:1500]}")

    context = "\n\n".join(context_parts)
    response_text = await call_gemini(history, message, context)

    return {
        "response": response_text,
        "ncbi_data": ncbi_data,
        "local": local,
        "sources": sources,
        "organism": org_key,
        "intents": intents
    }

# ============================================================================
# FASTAPI APP
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    db_init()
    yield

app = FastAPI(title="BioAI", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

class HistoryTurn(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    history: Optional[List[HistoryTurn]] = None

class TranslateRequest(BaseModel):
    sequence: str

class MutationRequest(BaseModel):
    reference: str
    sample: str

class GCRequest(BaseModel):
    sequence: str

@app.get("/")
async def root():
    return {
        "service": "BioAI",
        "status": "ok",
        "version": "1.0.0",
        "ai_model": GEMINI_MODEL,
        "ai_configured": GEMINI_API_KEY not in ("", "YOUR_KEY_HERE"),
        "organisms": [
            {"key": k, "scientific_name": v["scientific_name"], "common_name": v["common_name"]}
            for k, v in ORGANISMS.items()
        ]
    }

@app.get("/organisms")
async def list_organisms():
    return {"organisms": list(ORGANISMS.values())}

@app.get("/organism/{key}")
async def get_organism(key: str):
    if key not in ORGANISMS:
        raise HTTPException(status_code=404, detail="organism not found")
    return ORGANISMS[key]

@app.get("/gene/{organism}/{gene}")
async def get_gene(organism: str, gene: str):
    if organism not in ORGANISMS:
        raise HTTPException(status_code=404, detail="organism not found")
    return await fetch_gene_full(organism, gene)

@app.get("/sequence/{accession}")
async def get_sequence(accession: str):
    rec = await fetch_accession(accession)
    if rec.get("error"):
        raise HTTPException(status_code=404, detail=rec["error"])
    return rec

@app.get("/mrna/{organism}")
async def get_mrna(organism: str, gene: str = Query(...), limit: int = 4):
    if organism not in ORGANISMS:
        raise HTTPException(status_code=404, detail="organism not found")
    return {"records": await fetch_mrna_records(organism, gene, limit)}

@app.post("/analyze/translate")
async def post_translate(req: TranslateRequest):
    return translate_dna(req.sequence)

@app.post("/analyze/mutations")
async def post_mutations(req: MutationRequest):
    return detect_mutations(req.reference, req.sample)

@app.post("/analyze/gc")
async def post_gc(req: GCRequest):
    return gc_analysis(req.sequence)

@app.post("/chat")
async def chat(req: ChatRequest):
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    conv_id = req.conversation_id or str(uuid.uuid4())
    history = [{"role": h.role, "content": h.content} for h in (req.history or [])]
    result = await process(req.message.strip(), history)
    result["conversation_id"] = conv_id
    return JSONResponse(result)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    print(f"BioAI starting on http://localhost:{port}")
    print(f"Gemini configured: {GEMINI_API_KEY not in ('', 'YOUR_KEY_HERE')}")
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
