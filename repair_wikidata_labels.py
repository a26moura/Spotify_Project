"""Re-evaluate candidate matches including Wikidata's multilingual default labels."""
import json, hashlib, time, urllib.request, urllib.parse, unicodedata, re
from pathlib import Path
from datetime import datetime, timezone
OUT=Path(__file__).resolve().parent/'validacao'
CACHE=OUT/'respostas'
rows=json.loads((OUT/'resultados-brutos.json').read_text(encoding='utf-8'))
entities={}
for p in CACHE.glob('*.json'):
    for q,e in json.loads(p.read_text(encoding='utf-8'))['data'].get('entities',{}).items():
        dest=entities.setdefault(q,{})
        for k,v in e.items():
            if isinstance(v,dict): dest.setdefault(k,{}).update(v)
            else: dest[k]=v
def vals(e,p):
    return [s['mainsnak']['datavalue']['value']['id'] for s in e.get('claims',{}).get(p,[]) if s.get('rank')!='deprecated' and s.get('mainsnak',{}).get('datavalue',{}).get('type')=='wikibase-entityid']
def norm(s): return re.sub(r'[^\w]+',' ',''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if not unicodedata.combining(c))).strip()
def names(e): return [x['value'] for x in e.get('labels',{}).values()]+[x['value'] for a in e.get('aliases',{}).values() for x in a]
def label(e): return next((e['labels'][l]['value'] for l in ['pt','en','mul','es','fr','ja'] if l in e.get('labels',{})),e.get('id',''))
needed=set()
for row in rows:
    for c in row['wikidata'].get('search_candidates',[]):
        q=c['id']; needed.add(q)
        for p in ['P175','P136','P407']: needed.update(vals(entities.get(q,{}),p))
needed=sorted(needed)
for start in range(0,len(needed),40):
    ids=needed[start:start+40]
    params={'format':'json','action':'wbgetentities','ids':'|'.join(ids),'props':'labels|aliases','languages':'mul|en|pt|es|fr|ja'}
    url='https://www.wikidata.org/w/api.php?'+urllib.parse.urlencode(params)
    path=CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    if path.exists(): data=json.loads(path.read_text(encoding='utf-8'))['data']
    else:
        for attempt in range(3):
            try:
                time.sleep(2)
                req=urllib.request.Request(url,headers={'User-Agent':'PersonalMusicValidation/0.1 (non-commercial local research; Python urllib)'})
                with urllib.request.urlopen(req,timeout=25) as response: data=json.load(response)
                path.write_text(json.dumps({'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'data':data},ensure_ascii=False),encoding='utf-8')
                break
            except Exception:
                if attempt==2: raise
                time.sleep(15)
    for q,e in data.get('entities',{}).items():
        for field in ['labels','aliases']: entities.setdefault(q,{'id':q}).setdefault(field,{}).update(e.get(field,{}))
    print('Rótulos',min(start+40,len(needed)),'/',len(needed),flush=True)
for row in rows:
    matches=[]
    for c in row['wikidata'].get('search_candidates',[]):
        e=entities.get(c['id'],{})
        title_match=any(norm(n)==norm(row['query_title']) for n in names(e))
        artist_match=any(any(norm(n)==norm(a) for n in names(entities.get(p,{})) for a in row['track']['artists']) for p in vals(e,'P175'))
        types=set(vals(e,'P31'))
        if types & {'Q193977','Q482994'} and not types & {'Q7366','Q134556'}: continue
        if title_match and artist_match:
            matches.append({'id':e['id'],'label':label(e),'genres':[{'id':x,'label':label(entities.get(x,{'id':x}))} for x in vals(e,'P136')],'languages':[{'id':x,'label':label(entities.get(x,{'id':x}))} for x in vals(e,'P407')],'claims':{p:e.get('claims',{}).get(p,[]) for p in ['P136','P407','P175','P31']}})
    row['wikidata']['matches_before_label_audit']=row['wikidata'].get('matches',[])
    row['wikidata']['matches']=matches
(OUT/'resultados-brutos.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('Revisão de rótulos concluída',flush=True)
