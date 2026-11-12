import json, re, time, hashlib, unicodedata, urllib.request, urllib.parse, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'validacao'
CACHE = OUT / 'respostas'
CACHE.mkdir(parents=True, exist_ok=True)
POSITIONS = [1,2,3,4,11,12,13,14,15,16,17,18,19,20,23,27,28,29,32,43,47,50,53,54,57,65,81,84,89,100,117,124,126,130,143,191,200,218,229,266]
tracks = json.loads((ROOT/'musicas-curtidas.json').read_text(encoding='utf-8'))['tracks']
sample = [t for t in tracks if int(t['position']) in POSITIONS]
(OUT/'amostra.json').write_text(json.dumps(sample,ensure_ascii=False,indent=2),encoding='utf-8')
last_mb = 0
last_wd = 0

def get(url):
    global last_mb, last_wd
    path = CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))['data']
    for attempt in range(3):
        try:
            if 'musicbrainz.org' in url:
                time.sleep(max(0, 1.1-(time.monotonic()-last_mb)))
                last_mb = time.monotonic()
            if 'wikidata.org' in url:
                time.sleep(max(0, 2.0-(time.monotonic()-last_wd)))
                last_wd = time.monotonic()
            req=urllib.request.Request(url,headers={'User-Agent':'PersonalMusicValidation/0.1 (non-commercial local research; Python urllib)','Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=25) as resp: data=json.load(resp)
            path.write_text(json.dumps({'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'data':data},ensure_ascii=False),encoding='utf-8')
            return data
        except Exception as e:
            if attempt==2: raise
            time.sleep(15 if getattr(e,'code',None)==429 else 2+attempt*2)

def mb(entity,ident=None,**params):
    return get('https://musicbrainz.org/ws/2/'+entity+'/'+(ident or '')+'?'+urllib.parse.urlencode({'fmt':'json',**params}))
def wd(**params):
    return get('https://www.wikidata.org/w/api.php?'+urllib.parse.urlencode({'format':'json',**params}))
def entities(ids):
    ids=list(dict.fromkeys(ids))
    return wd(action='wbgetentities',ids='|'.join(ids),props='labels|aliases|descriptions|claims',languages='mul|en|pt|es|fr|ja').get('entities',{}) if ids else {}
def norm(s): return re.sub(r'[^\w]+',' ',''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if not unicodedata.combining(c))).strip()
def base_title(s):
    s=re.split(r'\s+-\s+(?:Ao Vivo|Live|from the series|Full Version)',s,flags=re.I)[0]
    return re.sub(r'\s*\((?:feat\.|with).*?\)','',s,flags=re.I).strip()
def label(e):
    labels=e.get('labels',{})
    return next((labels[l]['value'] for l in ['pt','en','mul','es','fr','ja'] if l in labels),e.get('id',''))
def values(e,p):
    return [s['mainsnak']['datavalue']['value']['id'] for s in e.get('claims',{}).get(p,[]) if s.get('rank')!='deprecated' and s.get('mainsnak',{}).get('datavalue',{}).get('type')=='wikibase-entityid']
def names(e):
    return [x['value'] for x in e.get('labels',{}).values()]+[x['value'] for xs in e.get('aliases',{}).values() for x in xs]
def credits(r): return [a['artist']['name'] for a in r.get('artist-credit',[]) if 'artist' in a]

previous_path=OUT/'resultados-brutos.json'
previous=json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else []
previous_by_position={r['track']['position']:r for r in previous}
results=[]
for index,t in enumerate(sample,1):
    existing=previous_by_position.get(t['position'])
    if existing and not existing.get('musicbrainz',{}).get('error') and not existing.get('wikidata',{}).get('error'):
        results.append(existing)
        print(f"{index}/40 cache: {t['title']}",flush=True)
        continue
    row={'track':t,'query_title':base_title(t['title']),'musicbrainz':{},'wikidata':{}}
    title=row['query_title']; artist=t['artists'][0]
    print(f"{index}/40 {t['title']} — {artist}",flush=True)
    try:
        q='recording:"'+title.replace('"','')+'" AND artist:"'+artist.replace('"','')+'"'
        found=mb('recording',query=q,limit=15).get('recordings',[])
        row['musicbrainz']['candidates']=[{'id':r['id'],'title':r['title'],'artists':credits(r),'disambiguation':r.get('disambiguation'),'score':r.get('score')} for r in found]
        candidates=[r for r in found if norm(r['title'])==norm(title) and any(norm(a)==norm(artist) for a in credits(r))]
        def rank(r):
            desc=r.get('disambiguation','').lower()
            live=any(x in desc for x in ['live','remix','mix','acoustic','instrumental','karaoke'])
            requested=any(x in t['title'].lower() for x in ['ao vivo','live','remix'])
            dj=any('DJ-mix' in rel.get('release-group',{}).get('secondary-types',[]) for rel in r.get('releases',[]))
            return (int(requested==live),int(not dj),int(not r.get('video')),len(r.get('releases',[])))
        if candidates:
            chosen=sorted(candidates,key=rank,reverse=True)[0]
            rec=mb('recording',chosen['id'],inc='genres+tags+artist-credits+releases+release-groups+work-rels+url-rels+isrcs')
            row['musicbrainz'].update({'selected_id':rec['id'],'selected_title':rec['title'],'selected_disambiguation':rec.get('disambiguation',''),'exact_recording_verified':False,'genres':rec.get('genres',[]),'tags':rec.get('tags',[]),'isrcs':rec.get('isrcs',[]),'relations':rec.get('relations',[])})
            groups=[]
            seen=set()
            for release in rec.get('releases',[]):
                rg=release.get('release-group',{})
                if not rg.get('id') or rg['id'] in seen: continue
                if any(x in rg.get('secondary-types',[]) for x in ['Compilation','DJ-mix']): continue
                seen.add(rg['id']); groups.append(rg)
            groups=sorted(groups,key=lambda g: (0 if norm(g['title'])==norm(title) else 1,0 if g.get('primary-type')=='Single' else 1))[:2]
            row['musicbrainz']['release_groups']=[]
            for group in groups:
                rg=mb('release-group',group['id'],inc='genres+tags')
                row['musicbrainz']['release_groups'].append({'id':rg['id'],'title':rg['title'],'genres':rg.get('genres',[]),'tags':rg.get('tags',[])})
            first_artist=next(a['artist'] for a in rec['artist-credit'] if 'artist' in a)
            ar=mb('artist',first_artist['id'],inc='genres+tags')
            row['musicbrainz']['artist']={'id':ar['id'],'name':ar['name'],'genres':ar.get('genres',[]),'tags':ar.get('tags',[])}
            works=[]
            for relation in rec.get('relations',[]):
                if relation.get('target-type')=='work':
                    w=mb('work',relation['work']['id'])
                    works.append({'id':w['id'],'title':w['title'],'languages':w.get('languages',[])})
            row['musicbrainz']['works']=works
        else: row['musicbrainz']['status']='nenhum candidato exato por titulo e primeiro artista'
    except Exception as e: row['musicbrainz']['error']=str(e)
    try:
        search=wd(action='wbsearchentities',search=title,language='en',uselang='en',type='item',limit=10).get('search',[])
        row['wikidata']['search_candidates']=[{'id':x['id'],'label':x.get('label'),'description':x.get('description')} for x in search]
        candidates=entities([x['id'] for x in search])
        performer_ids=[p for e in candidates.values() for p in values(e,'P175')]
        performers=entities(performer_ids)
        selected=[]
        for qid,e in candidates.items():
            types=set(values(e,'P31'))
            if types & {'Q193977','Q482994'} and not types & {'Q7366','Q134556'}: continue
            title_match=any(norm(n)==norm(title) for n in names(e))
            performer_match=any(any(norm(n)==norm(a) for n in names(performers.get(p,{})) for a in t['artists']) for p in values(e,'P175'))
            if title_match and performer_match: selected.append(e)
        row['wikidata']['matches']=[]
        for e in selected:
            ids=values(e,'P136')+values(e,'P407')
            labels=entities(ids)
            row['wikidata']['matches'].append({'id':e['id'],'label':label(e),'genres':[{'id':x,'label':label(labels.get(x,{'id':x}))} for x in values(e,'P136')],'languages':[{'id':x,'label':label(labels.get(x,{'id':x}))} for x in values(e,'P407')],'claims':{p:e.get('claims',{}).get(p,[]) for p in ['P136','P407','P175']}})
    except Exception as e: row['wikidata']['error']=str(e)
    results.append(row)
    (OUT/'resultados-brutos.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('  MB:',bool(row['musicbrainz'].get('selected_id')),'WD:',len(row['wikidata'].get('matches',[])),'errors:',row['musicbrainz'].get('error',''),row['wikidata'].get('error',''),flush=True)
print('Concluido',flush=True)
