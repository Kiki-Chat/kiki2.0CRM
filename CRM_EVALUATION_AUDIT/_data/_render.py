#!/usr/bin/env python3
"""Deterministic renderer: builds the structured audit deliverables from the
producer JSON evidence. Faithful, complete, no LLM omission risk."""
import json, glob, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))          # .../CRM_EVALUATION_AUDIT/_data
OUT  = os.path.dirname(BASE)                                # .../docs/audit
DATE = "2026-06-17"

DOMAIN_ORDER = ["AUTH","CUST","INQ","CASE","PROJ","APPT","EMP","INV","BILL","COMM","OUT","CALL","COP","KIKI"]
DOMAIN_LABEL = {
 "AUTH":"Authentication, Authorization, Roles & Multi-tenancy",
 "CUST":"Customers & Leads",
 "INQ":"Inquiries (Anfragen / ANF-)",
 "CASE":"Cases (Fälle / FL-)",
 "PROJ":"Projects (Projekte / PR-)",
 "APPT":"Appointments, Calendar, Scheduling & Technician Dispatch",
 "EMP":"Employees, Technicians, Vehicles & Absence",
 "INV":"Invoices, Cost Estimates (KVA) & Catalog",
 "BILL":"Stripe Billing, Usage Metering & Provisioning",
 "COMM":"Email & Notifications",
 "OUT":"Outbound Calls & Dispatch",
 "CALL":"Inbound Calls, Call Log, Post-call & Conversation Logic",
 "COP":"AI Copilot (in-CRM assistant)",
 "KIKI":"Kiki-Zentrale: Voice-Agent Configuration & ElevenLabs Sync",
}
# domains with live runtime confirmation in this audit (see RUNTIME_VALIDATION_REPORT.md)
RUNTIME_DOMAINS = {"AUTH","CUST","INQ","CASE","PROJ","APPT","OUT","CALL","KIKI"}

def esc(s):
    if s is None: return ""
    return str(s).replace("|","\\|").replace("\n"," ").strip()

def joinl(v, sep="; "):
    if v is None: return ""
    if isinstance(v,(list,tuple)): return sep.join(esc(x) for x in v if x not in (None,""))
    return esc(v)

def joinbr(v):
    return joinl(v, "<br>")

def load_rules():
    out={}
    for f in glob.glob(os.path.join(BASE,"rules","*.json")):
        p=os.path.basename(f)[:-5]
        out[p]=json.load(open(f))
    return out

def w(path, text):
    fp=os.path.join(OUT,path)
    open(fp,"w").write(text)
    print(f"  wrote {path} ({len(text):,} bytes)")

RULES = load_rules()
ALL_RULES=[]
for p in DOMAIN_ORDER:
    for r in RULES.get(p,{}).get("rules",[]):
        r["_domain"]=p; ALL_RULES.append(r)

CLASSES=["CLEAR","WELL_IMPLEMENTED","PARTIALLY_IMPLEMENTED","AMBIGUOUS","MISSING","UNDEFINED_BEHAVIOR","DEPRECATED","ORPHAN"]

# ---------------------------------------------------------------- BUSINESS_RULES.md
def render_business_rules():
    L=[f"# BUSINESS RULES — KikiJarvis CRM",""]
    L.append(f"*Authoritative, evidence-based catalog of every business rule observed in the codebase. Generated {DATE} from static code analysis; runtime-confirmed items are cross-referenced in `RUNTIME_VALIDATION_REPORT.md`.*\n")
    L.append(f"**Totals:** {len(ALL_RULES)} rules across {len(DOMAIN_ORDER)} domains.\n")
    L.append("**Classification legend:** `CLEAR` (unambiguous, evidenced) · `WELL_IMPLEMENTED` (clear + robust) · `PARTIALLY_IMPLEMENTED` · `AMBIGUOUS` · `MISSING` · `UNDEFINED_BEHAVIOR` · `DEPRECATED` · `ORPHAN`.\n")
    # global index
    L.append("## Domain Index\n")
    L.append("| Domain | Rules | Clearly-defined | Avg confidence |")
    L.append("|---|---|---|---|")
    for p in DOMAIN_ORDER:
        rs=RULES.get(p,{}).get("rules",[])
        if not rs: continue
        cd=sum(1 for r in rs if r.get("classification") in ("CLEAR","WELL_IMPLEMENTED"))
        avg=round(sum(r.get("confidence",0) for r in rs)/len(rs)) if rs else 0
        L.append(f"| **{p}** — {DOMAIN_LABEL[p]} | {len(rs)} | {cd}/{len(rs)} ({round(100*cd/len(rs))}%) | {avg} |")
    L.append("")
    fld=[("Description","description"),("Purpose","purpose"),("Trigger","trigger"),
         ("Preconditions","preconditions"),("Inputs","inputs"),("Validations","validations"),
         ("Actions","actions"),("System Effects","systemEffects"),("Outputs","outputs"),
         ("Failure Conditions","failureConditions"),("Dependencies","dependencies"),
         ("Related Rules","relatedRules"),("Affected Modules","affectedModules"),
         ("Affected APIs","affectedAPIs"),("Affected Tables","affectedTables"),
         ("Source References","sourceReferences"),("Evidence","evidence")]
    for p in DOMAIN_ORDER:
        rs=RULES.get(p,{}).get("rules",[])
        if not rs: continue
        L.append(f"\n---\n\n## {p} — {DOMAIN_LABEL[p]}\n")
        L.append("| Rule ID | Name | Classification | Conf |")
        L.append("|---|---|---|---|")
        for r in rs:
            L.append(f"| `{esc(r.get('id'))}` | {esc(r.get('name'))} | {esc(r.get('classification'))} | {r.get('confidence','')} |")
        L.append("")
        for r in rs:
            L.append(f"#### `{esc(r.get('id'))}` — {esc(r.get('name'))}")
            L.append(f"*Classification:* **{esc(r.get('classification'))}** · *Confidence:* {r.get('confidence','')}\n")
            for label,key in fld:
                v=r.get(key)
                if v in (None,"",[],{}): continue
                if isinstance(v,list):
                    L.append(f"- **{label}:**")
                    for x in v:
                        L.append(f"  - {esc(x)}")
                else:
                    L.append(f"- **{label}:** {esc(v)}")
            L.append("")
    w("BUSINESS_RULES.md","\n".join(L)+"\n")

# ---------------------------------------------------------------- TRACEABILITY_MATRIX.md
def render_traceability():
    L=["# TRACEABILITY MATRIX — KikiJarvis CRM",""]
    L.append(f"*Every business rule mapped to the code, APIs and tables that implement it. Generated {DATE}.*\n")
    orphans=[]
    for p in DOMAIN_ORDER:
        rs=RULES.get(p,{}).get("rules",[])
        if not rs: continue
        L.append(f"## {p} — {DOMAIN_LABEL[p]}\n")
        L.append("| Rule ID | Name | Affected Modules | APIs | Tables | Source Refs | Class | Conf |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in rs:
            mods=r.get("affectedModules") or []
            apis=r.get("affectedAPIs") or []
            tbls=r.get("affectedTables") or []
            if not mods and not apis and not tbls:
                orphans.append(r)
            L.append("| `%s` | %s | %s | %s | %s | %s | %s | %s |"%(
                esc(r.get("id")), esc(r.get("name")), joinbr(mods), joinbr(apis),
                joinbr(tbls), joinbr(r.get("sourceReferences")), esc(r.get("classification")), r.get("confidence","")))
        L.append("")
    L.append("## Orphan Rules (no module/API/table linkage)\n")
    if orphans:
        for r in orphans:
            L.append(f"- `{esc(r.get('id'))}` — {esc(r.get('name'))} ({esc(r.get('classification'))})")
    else:
        L.append("_None — every rule traces to at least one module, API, or table._")
    L.append("")
    w("TRACEABILITY_MATRIX.md","\n".join(L)+"\n")

# ---------------------------------------------------------------- FEATURE_TO_RULE_MATRIX.md
def render_feature_matrix():
    L=["# FEATURE → RULE MATRIX — KikiJarvis CRM",""]
    L.append(f"*Each discovered feature mapped to the rules that govern it (matched within-domain by shared module/API/table; falls back to all domain rules). Generated {DATE}.*\n")
    total_feat=0; matched_rule_ids=set()
    orphan_features=[]
    for p in DOMAIN_ORDER:
        dom=RULES.get(p,{})
        feats=dom.get("features",[]); rs=dom.get("rules",[])
        if not feats: continue
        L.append(f"## {p} — {DOMAIN_LABEL[p]}\n")
        L.append("| Feature | Rule IDs | Supporting Modules | APIs | DB Objects | Validation | Conf | Observed Risks |")
        L.append("|---|---|---|---|---|---|---|---|")
        for ft in feats:
            total_feat+=1
            fm=set(ft.get("modules") or []); fa=set(ft.get("apis") or []); ftab=set(ft.get("tables") or [])
            ids=[]
            for r in rs:
                rm=set(r.get("affectedModules") or []); ra=set(r.get("affectedAPIs") or []); rt=set(r.get("affectedTables") or [])
                if (fm & rm) or (fa & ra) or (ftab & rt):
                    ids.append(r.get("id"))
            if not ids:  # fallback: all domain rules share the feature's domain
                ids=[r.get("id") for r in rs]
            if not ids: orphan_features.append((p,ft.get("name")))
            matched_rule_ids.update(ids)
            L.append("| %s | %s | %s | %s | %s | %s | %s | %s |"%(
                esc(ft.get("name")), joinl([f"`{i}`" for i in ids],", "), joinbr(ft.get("modules")),
                joinbr(ft.get("apis")), joinbr(ft.get("tables")), esc(ft.get("validationStatus")),
                ft.get("confidence",""), joinbr(ft.get("risks"))))
        L.append("")
    all_ids={r.get("id") for r in ALL_RULES}
    orphan_rules=sorted(all_ids - matched_rule_ids)
    L.append("## Orphans\n")
    L.append(f"- **Features discovered:** {total_feat}")
    L.append(f"- **Orphan features (no governing rule):** {len(orphan_features)}" + (": " + ", ".join(f"{p}:{n}" for p,n in orphan_features) if orphan_features else " — none"))
    L.append(f"- **Orphan rules (not mapped to any feature):** {len(orphan_rules)}" + (": " + ", ".join(f"`{i}`" for i in orphan_rules) if orphan_rules else " — none"))
    L.append("")
    w("FEATURE_TO_RULE_MATRIX.md","\n".join(L)+"\n")

# ---------------------------------------------------------------- BUSINESS_RULE_COVERAGE.md
def render_coverage():
    n=len(ALL_RULES)
    by={c:0 for c in CLASSES}
    for r in ALL_RULES:
        by[r.get("classification","")]=by.get(r.get("classification",""),0)+1
    clearly=by.get("CLEAR",0)+by.get("WELL_IMPLEMENTED",0)
    partial=by.get("PARTIALLY_IMPLEMENTED",0)
    ambig=by.get("AMBIGUOUS",0)+by.get("MISSING",0)+by.get("UNDEFINED_BEHAVIOR",0)+by.get("ORPHAN",0)+by.get("DEPRECATED",0)
    total_feat=sum(len(RULES.get(p,{}).get("features",[])) for p in DOMAIN_ORDER)
    runtime_rules=sum(len(RULES.get(p,{}).get("rules",[])) for p in RUNTIME_DOMAINS)
    score=round(100*clearly/n) if n else 0
    L=["# BUSINESS RULE COVERAGE — KikiJarvis CRM",""]
    L.append(f"*Generated {DATE} from {n} extracted rules across {len(DOMAIN_ORDER)} domains and {total_feat} features.*\n")
    L.append("## Coverage Score\n")
    L.append(f"> **Coverage Score: {score}%**  \n> Clearly Defined (`CLEAR`+`WELL_IMPLEMENTED`): **{clearly}/{n} = {round(100*clearly/n)}%**  \n> Partially Implemented: **{partial}/{n} = {round(100*partial/n)}%**  \n> Ambiguous / Missing / Undefined / Orphan / Deprecated: **{ambig}/{n} = {round(100*ambig/n)}%**\n")
    L.append("**Justification:** the score is the share of rules classified `CLEAR` or `WELL_IMPLEMENTED` — i.e. behavior that is unambiguous in code and safe to document as authoritative. `PARTIALLY_IMPLEMENTED` rules work but have gaps; the remaining bucket needs product decisions or carries undefined behavior. See `AUDIT_REPORT.md` for the narrative and `RUNTIME_VALIDATION_REPORT.md` for live confirmation.\n")
    L.append("## Classification Breakdown\n")
    L.append("| Classification | Count | % |")
    L.append("|---|---|---|")
    for c in CLASSES:
        if by.get(c,0): L.append(f"| {c} | {by[c]} | {round(100*by[c]/n)}% |")
    L.append(f"| **Total** | **{n}** | 100% |\n")
    L.append("## Runtime Validation\n")
    L.append(f"- **Domains with live runtime confirmation** ({len(RUNTIME_DOMAINS)} of {len(DOMAIN_ORDER)}): {', '.join(sorted(RUNTIME_DOMAINS))} — covering ~{runtime_rules} rules ({round(100*runtime_rules/n)}% of all rules) touched by the DB / deployed-stack / ElevenLabs checks in `RUNTIME_VALIDATION_REPORT.md`.")
    L.append("- **Code-only domains** (no live runtime exercise this round): " + ", ".join(p for p in DOMAIN_ORDER if p not in RUNTIME_DOMAINS) + " — validated by static evidence; runtime procedures documented for outbound/email.")
    L.append("- Runtime confirmed: pipeline linkage, org-code numbering, status machines, emergency flagging, AI case grouping, outbound occasion taxonomy, DB write-persist round-trip, ElevenLabs prompt render. Unverified at runtime: ElevenLabs tool/webhook/audio (MCP simplified view), appointment proposal/reschedule states (no live rows).\n")
    L.append("## Per-Domain Coverage\n")
    L.append("| Domain | Rules | Features | Clearly-defined % | Avg conf | Runtime |")
    L.append("|---|---|---|---|---|---|")
    for p in DOMAIN_ORDER:
        rs=RULES.get(p,{}).get("rules",[]); fts=RULES.get(p,{}).get("features",[])
        if not rs: continue
        cd=sum(1 for r in rs if r.get("classification") in ("CLEAR","WELL_IMPLEMENTED"))
        avg=round(sum(r.get("confidence",0) for r in rs)/len(rs))
        L.append(f"| {p} | {len(rs)} | {len(fts)} | {round(100*cd/len(rs))}% | {avg} | {'✅' if p in RUNTIME_DOMAINS else '—'} |")
    L.append("")
    w("BUSINESS_RULE_COVERAGE.md","\n".join(L)+"\n")

# ---------------------------------------------------------------- WORKFLOW_DIAGRAMS.md
def render_workflows():
    wf=json.load(open(os.path.join(BASE,"workflows.json"))).get("workflows",[])
    L=["# WORKFLOW DIAGRAMS — KikiJarvis CRM",""]
    L.append(f"*End-to-end workflow traces with Mermaid flowcharts. Generated {DATE} from code-path analysis.*\n")
    L.append("## Index\n")
    for i,x in enumerate(wf,1): L.append(f"{i}. {esc(x.get('name'))}")
    L.append("")
    rows=[("Trigger","trigger"),("Inputs","inputs"),("Conditions","conditions"),
          ("Business Rules","businessRules"),("Actions","actions"),("Outputs","outputs"),
          ("Exceptions","exceptions"),("Failure Modes","failureModes"),("Dependencies","dependencies"),
          ("Source References","sourceReferences")]
    for i,x in enumerate(wf,1):
        L.append(f"\n---\n\n## {i}. {esc(x.get('name'))}\n")
        m=x.get("mermaid")
        if m:
            m=m.strip()
            if m.startswith("```"):  # strip stray fences
                m="\n".join(ln for ln in m.splitlines() if not ln.strip().startswith("```"))
            L.append("```mermaid"); L.append(m); L.append("```\n")
        L.append("| Aspect | Detail |")
        L.append("|---|---|")
        for label,key in rows:
            v=x.get(key)
            if v in (None,"",[]): continue
            L.append(f"| **{label}** | {joinbr(v)} |")
        if x.get("confidence") is not None:
            L.append(f"| **Confidence** | {x.get('confidence')} |")
        L.append("")
    w("WORKFLOW_DIAGRAMS.md","\n".join(L)+"\n")

# ---------------------------------------------------------------- SECURITY_OBSERVATION_REPORT.md
def render_security():
    obs=json.load(open(os.path.join(BASE,"security.json"))).get("observations",[])
    SEV=["CRITICAL","HIGH","MEDIUM","LOW","INFO"]
    rank={s:i for i,s in enumerate(SEV)}
    obs=sorted(obs,key=lambda o:(rank.get(o.get("severity","INFO"),9), o.get("id","")))
    counts={s:sum(1 for o in obs if o.get("severity")==s) for s in SEV}
    L=["# SECURITY OBSERVATION REPORT — KikiJarvis CRM",""]
    L.append(f"*Observations only — no fixes proposed (per audit scope). Generated {DATE} from static analysis; the final section adds live Supabase advisor findings. Confirm before acting.*\n")
    L.append("## Severity Summary\n")
    L.append("| " + " | ".join(SEV) + " | Total |")
    L.append("|" + "---|"*(len(SEV)+1))
    L.append("| " + " | ".join(str(counts[s]) for s in SEV) + f" | {len(obs)} |\n")
    L.append("## Observations (sorted by severity)\n")
    L.append("| ID | Title | Category | Severity | Affected Files | Conf | Verified |")
    L.append("|---|---|---|---|---|---|---|")
    for o in obs:
        L.append("| `%s` | %s | %s | **%s** | %s | %s | %s |"%(
            esc(o.get("id")), esc(o.get("title")), esc(o.get("category")), esc(o.get("severity")),
            joinbr(o.get("affectedFiles")), o.get("confidence",""), esc(o.get("verified"))))
    L.append("")
    L.append("## Detail\n")
    for o in obs:
        L.append(f"### `{esc(o.get('id'))}` — {esc(o.get('title'))}  ·  {esc(o.get('severity'))} / {esc(o.get('category'))}\n")
        if o.get("description"): L.append(f"{o.get('description')}\n")
        if o.get("affectedFiles"): L.append(f"- **Affected:** {joinl(o.get('affectedFiles'), ', ')}")
        if o.get("evidence"): L.append(f"- **Evidence:** {esc(o.get('evidence'))}")
        L.append(f"- **Confidence:** {o.get('confidence','')} · **Verified:** {esc(o.get('verified'))}\n")
    # runtime advisors
    try:
        rt=json.load(open(os.path.join(BASE,"runtime_db.json"))).get("securityAdvisors",{})
        L.append("---\n\n## Live Supabase Advisor Findings (runtime-verified)\n")
        rls=rt.get("rls_enabled_no_policy_INFO",[])
        L.append(f"- **RLS enabled but NO policy ({len(rls)} tables, INFO):** {', '.join('`'+t+'`' for t in rls)}.")
        L.append(f"  - *Interpretation:* {esc(rt.get('interpretation'))}")
        for wd in rt.get("warn",[]):
            L.append(f"- **WARN:** {esc(wd)}")
        L.append("")
    except Exception as e:
        L.append(f"\n_(runtime advisor merge skipped: {e})_\n")
    w("SECURITY_OBSERVATION_REPORT.md","\n".join(L)+"\n")

# ---------------------------------------------------------------- REPOSITORY_MAP.md
def mermaid_id(s):
    return "".join(c if c.isalnum() else "_" for c in str(s))[:40]

def render_repo_map():
    d=json.load(open(os.path.join(BASE,"repo_map.json")))
    L=["# REPOSITORY MAP — KikiJarvis CRM",""]
    L.append(f"*Structure, modules, tables, dependencies and data flows. Generated {DATE}.*\n")
    L.append("## Repository Structure\n")
    L.append("| Path | Role | Key Files |"); L.append("|---|---|---|")
    for s in d.get("structure",[]):
        L.append(f"| `{esc(s.get('path'))}` | {esc(s.get('role'))} | {joinbr(s.get('keyFiles'))} |")
    L.append("")
    L.append("## Backend Modules\n")
    L.append("| Area | Routes | Services |"); L.append("|---|---|---|")
    for m in d.get("backendModules",[]):
        L.append(f"| {esc(m.get('area'))} | {joinbr(m.get('routes'))} | {joinbr(m.get('services'))} |")
    L.append("")
    L.append("## Frontend Modules\n")
    L.append("| Area | Pages |"); L.append("|---|---|")
    for m in d.get("frontendModules",[]):
        L.append(f"| {esc(m.get('area'))} | {joinbr(m.get('pages'))} |")
    L.append("")
    L.append(f"## Database Tables ({len(d.get('dbTables',[]))})\n")
    L.append("| Table | Introduced By | Purpose |"); L.append("|---|---|---|")
    for t in d.get("dbTables",[]):
        L.append(f"| `{esc(t.get('table'))}` | {esc(t.get('introducedBy'))} | {esc(t.get('purpose'))} |")
    L.append("")
    L.append("## Module Relationship Diagram\n")
    L.append("```mermaid"); L.append("flowchart LR")
    seen=set()
    for e in d.get("dependencyEdges",[])[:40]:
        a=mermaid_id(e.get("from")); b=mermaid_id(e.get("to"))
        if not a or not b: continue
        for nid,lbl in ((a,e.get("from")),(b,e.get("to"))):
            if nid not in seen:
                seen.add(nid); L.append(f'  {nid}["{esc(lbl)}"]')
        L.append(f"  {a} --> {b}")
    L.append("```\n")
    L.append("### Dependency Edges\n")
    L.append("| From | To | Reason |"); L.append("|---|---|---|")
    for e in d.get("dependencyEdges",[]):
        L.append(f"| {esc(e.get('from'))} | {esc(e.get('to'))} | {esc(e.get('reason'))} |")
    L.append("")
    L.append("## Data Flows\n")
    L.append("```mermaid"); L.append("flowchart TD")
    for i,fl in enumerate(d.get("dataFlows",[])):
        steps=fl.get("steps") or []
        prev=None
        nm=mermaid_id(fl.get("name"))
        L.append(f'  subgraph F{i}["{esc(fl.get("name"))}"]')
        for j,st in enumerate(steps[:8]):
            sid=f"{nm}_{j}"
            L.append(f'  {sid}["{esc(st)[:48]}"]')
            if prev: L.append(f"  {prev} --> {sid}")
            prev=sid
        L.append("  end")
    L.append("```\n")
    for fl in d.get("dataFlows",[]):
        L.append(f"- **{esc(fl.get('name'))}:** {joinl(fl.get('steps'),' → ')}" + (f"  _(integrations: {joinl(fl.get('crossesIntegrations'),', ')})_" if fl.get('crossesIntegrations') else ""))
    L.append("")
    w("REPOSITORY_MAP.md","\n".join(L)+"\n")

# ---------------------------------------------------------------- INTEGRATION_DEPENDENCY_MAP.md
def render_integration():
    d=json.load(open(os.path.join(BASE,"repo_map.json")))
    ints=d.get("integrations",[]); envs=d.get("envVars",[])
    L=["# INTEGRATION & DEPENDENCY MAP — KikiJarvis CRM",""]
    L.append(f"*External integrations, their auth, the env vars they need, and failure modes. Generated {DATE}.*\n")
    L.append("## Integration Diagram\n")
    L.append("```mermaid"); L.append("flowchart LR"); L.append('  CRM["KikiJarvis Backend"]')
    for it in ints:
        nid=mermaid_id(it.get("name")); L.append(f'  {nid}["{esc(it.get("name"))}"]')
        dirn=(it.get("direction") or "").lower()
        if dirn=="inbound": L.append(f"  {nid} --> CRM")
        elif dirn=="both": L.append(f"  CRM <--> {nid}")
        else: L.append(f"  CRM --> {nid}")
    L.append("```\n")
    L.append(f"## Integrations ({len(ints)})\n")
    L.append("| Integration | Direction | Auth | Used By | Failure Mode | Evidence |")
    L.append("|---|---|---|---|---|---|")
    for it in ints:
        L.append("| **%s** | %s | %s | %s | %s | %s |"%(
            esc(it.get("name")), esc(it.get("direction")), esc(it.get("authMechanism")),
            joinbr(it.get("usedBy")), esc(it.get("failureMode")), esc(it.get("evidence"))))
    L.append("")
    req=[e for e in envs if e.get("required")]; opt=[e for e in envs if not e.get("required")]
    L.append(f"## Environment Variables ({len(envs)} — {len(req)} required)\n")
    L.append("| Env Var | Used For | Required |"); L.append("|---|---|---|")
    for e in envs:
        L.append(f"| `{esc(e.get('name'))}` | {esc(e.get('usedFor'))} | {'✅' if e.get('required') else '—'} |")
    L.append("")
    w("INTEGRATION_DEPENDENCY_MAP.md","\n".join(L)+"\n")

print("Rendering deterministic deliverables:")
render_business_rules()
render_traceability()
render_feature_matrix()
render_coverage()
render_workflows()
render_security()
render_repo_map()
render_integration()
print("Done.")
