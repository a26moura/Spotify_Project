import json, re, unicodedata
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'validacao'
data=json.loads((OUT/'resultados-brutos.json').read_text(encoding='utf-8'))
# Exclude visual-media and album-only Wikidata entities from direct song evidence.
# Full entity responses are kept separately, so decisions remain auditable.
cached_entities={}
for cache_file in (OUT/'respostas').glob('*.json'):
    cached_entities.update(json.loads(cache_file.read_text(encoding='utf-8'))['data'].get('entities',{}))
for result in data:
    valid=[]
    for match in result['wikidata'].get('matches',[]):
        entity=cached_entities.get(match['id'],{})
        types={s.get('mainsnak',{}).get('datavalue',{}).get('value',{}).get('id') for s in entity.get('claims',{}).get('P31',[])}
        if types & {'Q193977','Q482994'} and not types & {'Q7366','Q134556'}:
            continue
        valid.append(match)
    result['wikidata']['matches']=valid

def norm(s): return ''.join(c for c in unicodedata.normalize('NFKD',s.lower()) if not unicodedata.combining(c))
def broad(s):
    n=norm(s)
    if 'reggaeton' in n or 'regueton' in n: return ['Reggaeton']
    if 'sertanej' in n: return ['Sertanejo']
    if 'vallenato' in n: return ['Vallenato']
    if 'bachata' in n: return ['Bachata']
    if 'merengue' in n: return ['Merengue']
    if 'cumbia' in n: return ['Cumbia']
    if 'funk carioca' in n or 'baile funk' in n or 'funk brasileiro' in n or 'brazilian funk' in n: return ['Funk brasileiro']
    if 'trap' in n: return ['Trap']
    if any(x in n for x in ['hip hop','hip-hop','rap','hip hop']): return ['Rap / Hip-hop']
    if 'metal' in n or 'deathcore' in n: return ['Metal']
    if 'post-hardcore' in n: return ['Rock']
    out=[]
    if 'rock' in n or 'punk' in n: out.append('Rock')
    if 'pop' in n: out.append('Pop')
    if out: return out
    if any(x in n for x in ['rhythm and blues','rhythm & blues','r&b','rnb']): return ['R&B']
    if any(x in n for x in ['electronic','eletronica','house','trance','dubstep','drum and bass','edm','dance music','eurodance','dancehall']):
        return ['Dancehall'] if 'dancehall' in n else ['Eletrônica']
    if 'afrobeat' in n: return ['Afrobeats / Afrobeat']
    if 'amapiano' in n: return ['Amapiano']
    if 'jazz' in n: return ['Jazz']
    if 'soul' in n: return ['Soul']
    if 'country' in n: return ['Country']
    if 'folk' in n: return ['Folk']
    if 'reggae' in n: return ['Reggae']
    if 'funk'==n: return ['Funk / Soul']
    return []

LANG={'eng':'Inglês','spa':'Espanhol','por':'Português','fra':'Francês','fre':'Francês','jpn':'Japonês','kor':'Coreano','glg':'Galego','ara':'Árabe','rus':'Russo'}
def clean(s): return str(s).replace('|','/').replace('\n',' ')
rows=[]
for i,r in enumerate(data,1):
    mb=r['musicbrainz']; wd=r['wikidata']; t=r['track']; ev=[]
    if mb.get('selected_id'):
        ev.append({'level':'faixa','source':'MusicBrainz','url':'https://musicbrainz.org/recording/'+mb['selected_id'],'genres':mb.get('genres',[])})
    for m in wd.get('matches',[]):
        ev.append({'level':'obra/faixa','source':'Wikidata','url':'https://www.wikidata.org/wiki/'+m['id'],'genres':[{'name':g['label'],'count':None} for g in m['genres']]})
    for g in mb.get('release_groups',[]):
        ev.append({'level':'lançamento','source':g['title'],'url':'https://musicbrainz.org/release-group/'+g['id'],'genres':g.get('genres',[])})
    a=mb.get('artist',{})
    if a: ev.append({'level':'artista','source':a['name'],'url':'https://musicbrainz.org/artist/'+a['id'],'genres':a.get('genres',[])})
    direct=[e for e in ev if e['level'] in ['faixa','obra/faixa'] and e['genres']]
    contextual=[e for e in ev if e['level']=='lançamento' and e['genres']]
    artist=[e for e in ev if e['level']=='artista' and e['genres']]
    chosen=direct or contextual or artist
    level='Direta' if direct else ('Lançamento' if contextual else ('Artista' if artist else 'Sem gênero'))
    genres=[]; used=[]; ignored=[]
    for e in chosen:
        positive=[g for g in e['genres'] if g.get('count') is None or g['count']>0]
        maxcount=max([g.get('count') or 0 for g in positive],default=0)
        for g in positive:
            # A conservative transparent vote filter, not calibrated confidence.
            if maxcount>=3 and g.get('count') is not None and g['count'] < 0.75*maxcount:
                ignored.append(g['name']); continue
            cats=broad(g['name'])
            if cats: genres.extend(cats); used.append(g['name'])
            else: ignored.append(g['name'])
    genres=list(dict.fromkeys(genres))
    languages=[]; lang_sources=[]
    for m in wd.get('matches',[]):
        for lang in m['languages']: languages.append(lang['label'].capitalize()); lang_sources.append('https://www.wikidata.org/wiki/'+m['id'])
    for w in mb.get('works',[]):
        for lang in w.get('languages',[]):
            if lang not in ['und','mul','zxx']: languages.append(LANG.get(lang,lang)); lang_sources.append('https://musicbrainz.org/work/'+w['id'])
    languages=list(dict.fromkeys(languages))
    notes=[]
    if mb.get('error') or wd.get('error'): notes.append('Falha técnica em consulta; não equivale a ausência no catálogo.')
    if not mb.get('selected_id') and not wd.get('matches'): notes.append('Identidade não localizada pelo método limitado de busca.')
    if any(x in t['title'].lower() for x in ['ao vivo','live','remix']): notes.append('Conferir versão ao vivo/remix antes de aceitar; o candidato pode ser de outra versão.')
    if mb.get('selected_disambiguation'): notes.append('Candidato MusicBrainz: '+mb['selected_disambiguation'])
    if level=='Artista': notes.append('Hipótese pelo artista; não confirma o estilo desta faixa.')
    if level=='Lançamento': notes.append('Contexto de lançamento; não é gênero específico da faixa.')
    if not genres: notes.append('Sem sugestão por regra; classificar manualmente.')
    if len(genres)>3: notes.append('Muitas categorias: verificar conflitos e reduzir.')
    if ignored: notes.append('Etiquetas não usadas na proposta (votos baixos ou sem regra): '+', '.join(dict.fromkeys(ignored)))
    rows.append({'sample_id':i,'library_position':t['position'],'title':t['title'],'artists':t['artists'],'spotify_url':t['url'],'suggested_genres':genres,'documented_languages':languages,'evidence_level':level,'evidence':ev,'language_sources':list(dict.fromkeys(lang_sources)),'notes':notes,'decision':'pendente','corrected_genres':[],'corrected_languages':[],'review_comment':''})

stats={'sample_size':len(rows),'musicbrainz_candidates':sum(bool(r['musicbrainz'].get('selected_id')) for r in data),'wikidata_candidates':sum(bool(r['wikidata'].get('matches')) for r in data),'identified_any':sum(bool(r['musicbrainz'].get('selected_id') or r['wikidata'].get('matches')) for r in data),'evidence_levels':dict(Counter(r['evidence_level'] for r in rows)),'with_suggestion':sum(bool(r['suggested_genres']) for r in rows),'with_language':sum(bool(r['documented_languages']) for r in rows),'technical_errors':sum(bool(r['musicbrainz'].get('error') or r['wikidata'].get('error')) for r in data),'human_reviewed':0,'acceptance_rate':None}
(OUT/'revisao-40.json').write_text(json.dumps({'metrics':stats,'tracks':rows},ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# Revisão das 40 músicas','', 'Estudo exploratório pessoal — MusicBrainz e Wikidata. Sugestões ainda não aprovadas por você.','', '## Resultado da consulta','']
lines += [f'- Amostra: {len(rows)} faixas escolhidas intencionalmente, sem representatividade estatística.',f"- Candidatos por título e artista: {stats['identified_any']}/{len(rows)}. A gravação exata do Spotify não foi confirmada por ISRC.",f"- MusicBrainz: {stats['musicbrainz_candidates']}; Wikidata: {stats['wikidata_candidates']} (há sobreposição).",f"- Evidência de gênero: {stats['evidence_levels']}.",f"- Sugestão por regras: {stats['with_suggestion']}; idioma documentado: {stats['with_language']}.",f"- Falhas técnicas: {stats['technical_errors']}.",'- Aceitação e precisão: ainda não medidas. Exigem sua revisão.','', '## Como revisar','', 'Em Decisão, substitua **pendente** por **aceitar**, **corrigir** ou **não sei**. Preencha Correção quando necessário. Gêneros e idiomas podem ter vários valores. Você também pode responder no chat com os números da amostra.','', 'Direta = gênero no registro musical candidato. Lançamento = contexto do álbum/single. Artista = hipótese mais fraca. “—” significa sem sugestão/evidência suficiente, não ausência real do gênero ou idioma.','', '| # | Música / artistas | Gêneros sugeridos | Idioma documentado | Evidência | Decisão | Correção |','|---|---|---|---|---|---|---|']
for r in rows:
    lines.append(f"| {r['sample_id']} | [{clean(r['title'])}]({r['spotify_url']}) — {clean(', '.join(r['artists']))} | {clean(', '.join(r['suggested_genres']) or '—')} | {clean(', '.join(r['documented_languages']) or '—')} | {r['evidence_level']} | pendente | |")
lines+=['','## Evidências por faixa','']
for r in rows:
    lines += [f"### {r['sample_id']}. {r['title']}",'',f"Posição original: {r['library_position']}. Artistas: {', '.join(r['artists'])}.",'']
    for e in r['evidence']:
        tags=', '.join(g['name']+(f" ({g['count']} votos)" if g.get('count') is not None else '') for g in e['genres']) or 'nenhum gênero registrado na resposta'
        lines.append(f"- {e['level']} — [{e['source']}]({e['url']}): {tags}.")
    for url in r['language_sources']: lines.append(f'- [Fonte do idioma]({url}).')
    for n in r['notes']: lines.append('- '+n)
    lines.append('')
lines += ['## Limites e atribuição','', 'Fontes: MusicBrainz e seus contribuidores (associações de gênero: CC BY-NC-SA 3.0) e Wikidata (dados estruturados CC0). Este relatório é pessoal e não comercial; os trechos derivados de associações de gênero do MusicBrainz seguem CC BY-NC-SA 3.0. Consulte [metodologia](METODOLOGIA.md) e [licença MusicBrainz](https://musicbrainz.org/doc/About/Data_License).','', 'Filtro experimental: em conjuntos com máximo de pelo menos 3 votos, usar apenas etiquetas com pelo menos 75% desse máximo. O filtro reduz ruído, mas pode eliminar gêneros válidos; não é uma probabilidade de acerto. Categorias são mapeadas pelas regras de build_review.py. Não há classificação de áudio nem inferência por nacionalidade.','', 'A classificação “Latinas” fica pendente de uma definição editorial; não foi inferida a partir do espanhol. A lista de faixas e dados pessoais não deve ser publicada automaticamente.']
(OUT/'revisao-40.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(stats,ensure_ascii=True,indent=2))
